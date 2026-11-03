import * as cdk from 'aws-cdk-lib';
import * as dynamodb from 'aws-cdk-lib/aws-dynamodb';
import * as kms from 'aws-cdk-lib/aws-kms';
import * as s3 from 'aws-cdk-lib/aws-s3';
import { Construct } from 'constructs';

/**
 * Single-table DynamoDB design, partitioned by tenant:
 *   PK = TENANT#<id>   SK = META | USER#<sub> | PLUGIN#<id> | CUSTOMER#<id> | MSG#<id> | AUDIT#<ts>#<id>
 * Every access path is keyed by tenant, so a query can never cross tenants.
 */
export class DataStack extends cdk.Stack {
  readonly table: dynamodb.Table;
  readonly docsBucket: s3.Bucket;
  readonly dataKey: kms.Key;

  constructor(scope: Construct, id: string, props: cdk.StackProps) {
    super(scope, id, props);

    this.dataKey = new kms.Key(this, 'DataKey', {
      enableKeyRotation: true,
      description: 'Hivemate tenant data encryption',
    });

    this.table = new dynamodb.Table(this, 'Table', {
      partitionKey: { name: 'PK', type: dynamodb.AttributeType.STRING },
      sortKey: { name: 'SK', type: dynamodb.AttributeType.STRING },
      billingMode: dynamodb.BillingMode.PAY_PER_REQUEST,
      encryption: dynamodb.TableEncryption.CUSTOMER_MANAGED,
      encryptionKey: this.dataKey,
      pointInTimeRecoverySpecification: { pointInTimeRecoveryEnabled: true },
      removalPolicy: cdk.RemovalPolicy.DESTROY, // dev stage; flip to RETAIN for prod
    });
    // Look up a tenant by its inbound identifier (email address, WhatsApp number, site key)
    this.table.addGlobalSecondaryIndex({
      indexName: 'ChannelIndex',
      partitionKey: { name: 'GSI1PK', type: dynamodb.AttributeType.STRING },
      sortKey: { name: 'GSI1SK', type: dynamodb.AttributeType.STRING },
    });

    // Tenant documents live under s3://bucket/<tenantId>/...
    this.docsBucket = new s3.Bucket(this, 'DocsBucket', {
      encryption: s3.BucketEncryption.KMS,
      encryptionKey: this.dataKey,
      blockPublicAccess: s3.BlockPublicAccess.BLOCK_ALL,
      enforceSSL: true,
      versioned: true,
      removalPolicy: cdk.RemovalPolicy.DESTROY,
      autoDeleteObjects: true,
      cors: [{
        allowedMethods: [s3.HttpMethods.POST, s3.HttpMethods.PUT, s3.HttpMethods.GET],
        allowedOrigins: ['http://localhost:3000'],
        allowedHeaders: ['*'],
      }],
    });

    new cdk.CfnOutput(this, 'TableName', { value: this.table.tableName });
    new cdk.CfnOutput(this, 'DocsBucketName', { value: this.docsBucket.bucketName });
  }
}
