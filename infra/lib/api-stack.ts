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
import * as ses from 'aws-cdk-lib/aws-ses';
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
    const senderEmail = this.node.tryGetContext('senderEmail') as string;
    if (!senderEmail) throw new Error('Pass -c senderEmail=you@example.com (CI: SENDER_EMAIL variable)');
    // SES emails a verification link to this address; sending is blocked until it is clicked.
    new ses.EmailIdentity(this, 'SenderIdentity', { identity: ses.Identity.email(senderEmail) });
    const sendMail = new iam.PolicyStatement({
      actions: ['ses:SendEmail'],
      // In the SES sandbox AWS also authorizes against each (verified) recipient identity, hence the wildcard.
      resources: [`arn:aws:ses:${this.region}:${this.account}:identity/*`],
    });
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
        SENDER_EMAIL: senderEmail,
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
    apiFn.addToRolePolicy(sendMail);
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
    emailFn.addToRolePolicy(sendMail);
    emailFn.addEventSource(new SqsEventSource(props.emailQueue, {
      batchSize: 5,
      reportBatchItemFailures: true,
      // The account-wide Lambda limit is small (10 on a new account); keep the AI worker from starving the API.
      maxConcurrency: 2,
    }));

    // ---- Conversation agent: web/WhatsApp chat, leads. Own Lambda: multi-step Bedrock calls need a longer timeout. ----
    const aiEnv = {
      ...common.environment,
      BEDROCK_MODEL_ID: modelId,
      GUARDRAIL_ID: props.guardrailId,
      GUARDRAIL_VERSION: props.guardrailVersion,
      WHATSAPP_REGION: (this.node.tryGetContext('whatsappRegion') as string) ?? 'ap-southeast-1',
    };
    const aiPolicies = [
      new iam.PolicyStatement({
        actions: ['bedrock:InvokeModel', 'bedrock:Converse'],
        resources: ['arn:aws:bedrock:*::foundation-model/*', `arn:aws:bedrock:*:${this.account}:inference-profile/*`],
      }),
      new iam.PolicyStatement({
        actions: ['bedrock:ApplyGuardrail'],
        resources: [`arn:aws:bedrock:${this.region}:${this.account}:guardrail/${props.guardrailId}`],
      }),
      new iam.PolicyStatement({ actions: ['bedrock:Retrieve'], resources: [props.knowledgeBaseArn] }),
      sendMail,
    ];
    const chatFn = new lambda.Function(this, 'ChatFn', {
      ...common, handler: 'src.api.chat.handler', timeout: cdk.Duration.seconds(29), memorySize: 512, environment: aiEnv,
    });
    props.table.grantReadWriteData(chatFn);
    aiPolicies.forEach((st) => chatFn.addToRolePolicy(st));

    // WhatsApp text adapter: AWS End User Messaging Social -> SNS -> this Lambda (subscription is made by the owner, see README).
    const whatsappFn = new lambda.Function(this, 'WhatsAppFn', {
      ...common, handler: 'src.channels.whatsapp.handler', timeout: cdk.Duration.seconds(60), memorySize: 512, environment: aiEnv,
    });
    props.table.grantReadWriteData(whatsappFn);
    aiPolicies.forEach((st) => whatsappFn.addToRolePolicy(st));
    whatsappFn.addToRolePolicy(new iam.PolicyStatement({
      actions: ['social-messaging:SendWhatsAppMessage'],
      resources: [`arn:aws:social-messaging:*:${this.account}:phone-number-id/*`],
    }));
    whatsappFn.addPermission('FromSns', { principal: new iam.ServicePrincipal('sns.amazonaws.com'), sourceAccount: this.account });
    new cdk.CfnOutput(this, 'WhatsAppFnArn', { value: whatsappFn.functionArn });

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
    // Browser preflight carries no token; without this the JWT authorizer rejects it with 401.
    api.addRoutes({
      path: '/{proxy+}',
      methods: [apigwv2.HttpMethod.OPTIONS],
      integration: new HttpLambdaIntegration('PreflightInt', apiFn),
      authorizer: new apigwv2.HttpNoneAuthorizer(),
    });
    const chatInt = new HttpLambdaIntegration('ChatInt', chatFn);
    [['/chat', [apigwv2.HttpMethod.POST]], ['/conversations', [apigwv2.HttpMethod.GET]],
     ['/conversations/{id}', [apigwv2.HttpMethod.GET]], ['/conversations/{id}/status', [apigwv2.HttpMethod.POST]],
     ['/leads', [apigwv2.HttpMethod.GET]], ['/channels/whatsapp', [apigwv2.HttpMethod.PUT]],
     ['/channels/web', [apigwv2.HttpMethod.GET, apigwv2.HttpMethod.PUT]],
    ].forEach(([path, methods]) => api.addRoutes({ path: path as string, methods: methods as apigwv2.HttpMethod[], integration: chatInt }));
    api.addRoutes({
      path: '/{proxy+}',
      methods: [apigwv2.HttpMethod.GET, apigwv2.HttpMethod.POST, apigwv2.HttpMethod.PUT, apigwv2.HttpMethod.DELETE, apigwv2.HttpMethod.PATCH],
      integration: new HttpLambdaIntegration('ApiInt', apiFn),
    });

    new cdk.CfnOutput(this, 'ApiUrl', { value: api.apiEndpoint });

    // ---- Public website chat: separate API so open CORS and tight throttling never touch the authenticated API ----
    const publicChatFn = new lambda.Function(this, 'PublicChatFn', {
      ...common, handler: 'src.channels.web.handler', timeout: cdk.Duration.seconds(29), memorySize: 512, environment: aiEnv,
    });
    props.table.grantReadWriteData(publicChatFn);
    aiPolicies.forEach((st) => publicChatFn.addToRolePolicy(st));
    const publicApi = new apigwv2.HttpApi(this, 'PublicApi', {
      apiName: 'hivemate-public-chat',
      corsPreflight: { allowOrigins: ['*'], allowMethods: [apigwv2.CorsHttpMethod.GET, apigwv2.CorsHttpMethod.POST], allowHeaders: ['content-type'] },
    });
    const publicInt = new HttpLambdaIntegration('PublicChatInt', publicChatFn);
    publicApi.addRoutes({ path: '/widget.js', methods: [apigwv2.HttpMethod.GET], integration: publicInt });
    publicApi.addRoutes({ path: '/info', methods: [apigwv2.HttpMethod.GET], integration: publicInt });
    publicApi.addRoutes({ path: '/chat', methods: [apigwv2.HttpMethod.POST], integration: publicInt });
    // Burst/steady limits across the whole public API; the account-wide Lambda quota is small.
    (publicApi.defaultStage!.node.defaultChild as apigwv2.CfnStage).defaultRouteSettings = { throttlingBurstLimit: 10, throttlingRateLimit: 5 };
    new cdk.CfnOutput(this, 'PublicChatUrl', { value: publicApi.apiEndpoint });
  }
}
