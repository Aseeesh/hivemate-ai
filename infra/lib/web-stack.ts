import * as cdk from 'aws-cdk-lib';
import * as s3 from 'aws-cdk-lib/aws-s3';
import * as cloudfront from 'aws-cdk-lib/aws-cloudfront';
import * as origins from 'aws-cdk-lib/aws-cloudfront-origins';
import { Construct } from 'constructs';

/** Static hosting for the Next.js dashboard: private S3 bucket behind CloudFront (HTTPS, default *.cloudfront.net domain). */
export class WebStack extends cdk.Stack {
  constructor(scope: Construct, id: string, props: cdk.StackProps) {
    super(scope, id, props);

    const bucket = new s3.Bucket(this, 'SiteBucket', {
      blockPublicAccess: s3.BlockPublicAccess.BLOCK_ALL,
      encryption: s3.BucketEncryption.S3_MANAGED,
      enforceSSL: true,
      removalPolicy: cdk.RemovalPolicy.DESTROY, // site is rebuilt from the repo
      autoDeleteObjects: true,
    });

    // Static export writes /dashboard/index.html; S3 has no directory index, so rewrite "/x/" to "/x/index.html".
    const rewrite = new cloudfront.Function(this, 'IndexRewrite', {
      runtime: cloudfront.FunctionRuntime.JS_2_0,
      code: cloudfront.FunctionCode.fromInline(
        `function handler(event) { var r = event.request; if (r.uri.endsWith('/')) r.uri += 'index.html'; else if (!r.uri.split('/').pop().includes('.')) r.uri += '/index.html'; return r; }`),
    });

    const headers = new cloudfront.ResponseHeadersPolicy(this, 'Headers', {
      securityHeadersBehavior: {
        strictTransportSecurity: { accessControlMaxAge: cdk.Duration.days(365), includeSubdomains: true, override: true },
        contentTypeOptions: { override: true },
        frameOptions: { frameOption: cloudfront.HeadersFrameOption.DENY, override: true },
        referrerPolicy: { referrerPolicy: cloudfront.HeadersReferrerPolicy.STRICT_ORIGIN_WHEN_CROSS_ORIGIN, override: true },
        // Next.js emits inline bootstrap scripts, so script-src needs 'unsafe-inline'. connect-src lists only what the app calls.
        contentSecurityPolicy: {
          override: true,
          contentSecurityPolicy: [
            "default-src 'self'", "script-src 'self' 'unsafe-inline'", "style-src 'self' 'unsafe-inline'", "img-src 'self' data:",
            `connect-src 'self' https://*.execute-api.${this.region}.amazonaws.com https://cognito-idp.${this.region}.amazonaws.com https://*.s3.${this.region}.amazonaws.com`,
            "frame-ancestors 'none'", "base-uri 'self'", "form-action 'self' https://*.s3." + this.region + '.amazonaws.com',
          ].join('; '),
        },
      },
    });

    const dist = new cloudfront.Distribution(this, 'Dist', {
      defaultRootObject: 'index.html',
      priceClass: cloudfront.PriceClass.PRICE_CLASS_100,
      minimumProtocolVersion: cloudfront.SecurityPolicyProtocol.TLS_V1_2_2021,
      defaultBehavior: {
        origin: origins.S3BucketOrigin.withOriginAccessControl(bucket),
        viewerProtocolPolicy: cloudfront.ViewerProtocolPolicy.REDIRECT_TO_HTTPS,
        responseHeadersPolicy: headers,
        functionAssociations: [{ function: rewrite, eventType: cloudfront.FunctionEventType.VIEWER_REQUEST }],
      },
      errorResponses: [{ httpStatus: 403, responseHttpStatus: 404, responsePagePath: '/404.html' }, { httpStatus: 404, responsePagePath: '/404.html' }],
    });

    new cdk.CfnOutput(this, 'SiteBucketName', { value: bucket.bucketName });
    new cdk.CfnOutput(this, 'DistributionId', { value: dist.distributionId });
    new cdk.CfnOutput(this, 'SiteUrl', { value: `https://${dist.distributionDomainName}` });
  }
}
