import * as cdk from 'aws-cdk-lib';
import * as apigwv2 from 'aws-cdk-lib/aws-apigatewayv2';
import { HttpJwtAuthorizer } from 'aws-cdk-lib/aws-apigatewayv2-authorizers';
import { HttpLambdaIntegration } from 'aws-cdk-lib/aws-apigatewayv2-integrations';
import * as cognito from 'aws-cdk-lib/aws-cognito';
import * as dynamodb from 'aws-cdk-lib/aws-dynamodb';
import * as events from 'aws-cdk-lib/aws-events';
import * as iam from 'aws-cdk-lib/aws-iam';
import * as kms from 'aws-cdk-lib/aws-kms';
import * as lambda from 'aws-cdk-lib/aws-lambda';
import { SqsEventSource } from 'aws-cdk-lib/aws-lambda-event-sources';
import * as s3 from 'aws-cdk-lib/aws-s3';
import * as sqs from 'aws-cdk-lib/aws-sqs';
import * as path from 'path';
import { Construct } from 'constructs';

interface ApiStackProps extends cdk.StackProps {
  table: dynamodb.ITable;
  docsBucket: s3.IBucket;
  dataKey: kms.IKey;
  userPool: cognito.IUserPool;
  userPoolClient: cognito.IUserPoolClient;
  bus: events.IEventBus;
  emailQueue: sqs.IQueue;
  guardrailId: string;
  guardrailVersion: string;
  knowledgeBaseId: string;
  knowledgeBaseArn: string;
  dataSourceId: string;
}

export class ApiStack extends cdk.Stack {
  constructor(scope: Construct, id: string, props: ApiStackProps) {
    super(scope, id, props);

    const code = lambda.Code.fromAsset(path.join(__dirname, '../../services'), {
      exclude: ['tests', '**/__pycache__', '*.pyc'],
    });
    const modelId = this.node.tryGetContext('bedrockModelId') as string;
    const common = {
      runtime: lambda.Runtime.PYTHON_3_13,
      code,
      architecture: lambda.Architecture.ARM_64,
      tracing: lambda.Tracing.ACTIVE,
      environment: {
        TABLE_NAME: props.table.tableName,
        DOCS_BUCKET: props.docsBucket.bucketName,
        EVENT_BUS: props.bus.eventBusName,
        MANIFEST_DIR: '/var/task/manifests',
        POWERTOOLS_SERVICE_NAME: 'hivemate',
        KNOWLEDGE_BASE_ID: props.knowledgeBaseId,
        DATA_SOURCE_ID: props.dataSourceId,
      },
    };

    // ---- Control-plane API: tenants, plugin registry, per-tenant plugin config ----
    const apiFn = new lambda.Function(this, 'ApiFn', {
      ...common,
      handler: 'src.api.handler.handler',
      timeout: cdk.Duration.seconds(15),
    });
    props.table.grantReadWriteData(apiFn);
    props.bus.grantPutEventsTo(apiFn);
    props.docsBucket.grantReadWrite(apiFn); // prefix scoping is enforced in code (tenant prefix)
    apiFn.addToRolePolicy(new iam.PolicyStatement({
      actions: ['bedrock:StartIngestionJob', 'bedrock:ListIngestionJobs', 'bedrock:GetIngestionJob'],
      resources: [props.knowledgeBaseArn],
    }));

    // ---- Email Automation plugin worker: SQS -> retrieve -> Bedrock -> approval gate ----
    const emailFn = new lambda.Function(this, 'EmailPluginFn', {
      ...common,
      handler: 'src.plugins.email.processor.handler',
      timeout: cdk.Duration.seconds(60),
      memorySize: 512,
      environment: {
        ...common.environment,
        BEDROCK_MODEL_ID: modelId,
        GUARDRAIL_ID: props.guardrailId,
        GUARDRAIL_VERSION: props.guardrailVersion,
      },
    });
    props.table.grantReadWriteData(emailFn);
    emailFn.addToRolePolicy(new iam.PolicyStatement({
      actions: ['bedrock:InvokeModel', 'bedrock:Converse', 'bedrock:ApplyGuardrail'],
      resources: [
        'arn:aws:bedrock:*::foundation-model/*',
        `arn:aws:bedrock:*:${this.account}:inference-profile/*`,
        `arn:aws:bedrock:${this.region}:${this.account}:guardrail/${props.guardrailId}`,
      ],
    }));
    emailFn.addToRolePolicy(new iam.PolicyStatement({
      actions: ['bedrock:Retrieve'],
      resources: [props.knowledgeBaseArn],
    }));
    emailFn.addEventSource(new SqsEventSource(props.emailQueue, {
      batchSize: 5,
      reportBatchItemFailures: true,
    }));

    // ---- HTTP API with Cognito JWT authorizer ----
    const authorizer = new HttpJwtAuthorizer('Jwt',
      `https://cognito-idp.${this.region}.amazonaws.com/${props.userPool.userPoolId}`,
      { jwtAudience: [props.userPoolClient.userPoolClientId] });

    const api = new apigwv2.HttpApi(this, 'HttpApi', {
      apiName: 'hivemate-api',
      corsPreflight: {
        allowOrigins: ['http://localhost:3000'],
        allowMethods: [apigwv2.CorsHttpMethod.ANY],
        allowHeaders: ['authorization', 'content-type'],
      },
      defaultAuthorizer: authorizer,
    });
    api.addRoutes({
      path: '/{proxy+}',
      methods: [apigwv2.HttpMethod.ANY],
      integration: new HttpLambdaIntegration('ApiInt', apiFn),
    });

    new cdk.CfnOutput(this, 'ApiUrl', { value: api.apiEndpoint });
  }
}
