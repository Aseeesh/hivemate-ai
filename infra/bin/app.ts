import * as cdk from 'aws-cdk-lib';
import { DataStack } from '../lib/data-stack';
import { AuthStack } from '../lib/auth-stack';
import { EventsStack } from '../lib/events-stack';
import { AiStack } from '../lib/ai-stack';
import { ApiStack } from '../lib/api-stack';
import { CostStack } from '../lib/cost-stack';

const app = new cdk.App();
const stage = app.node.tryGetContext('stage') as string;
const env = {
  account: process.env.CDK_DEFAULT_ACCOUNT,
  region: process.env.CDK_DEFAULT_REGION ?? 'ap-southeast-2',
};
const prefix = `hivemate-${stage}`;

const data = new DataStack(app, `${prefix}-data`, { env });
const events = new EventsStack(app, `${prefix}-events`, { env });
const ai = new AiStack(app, `${prefix}-ai`, { env, docsBucket: data.docsBucket, dataKey: data.dataKey });
const auth = new AuthStack(app, `${prefix}-auth`, { env, table: data.table });
const api = new ApiStack(app, `${prefix}-api`, {
  env,
  table: data.table,
  docsBucket: data.docsBucket,
  dataKey: data.dataKey,
  userPool: auth.userPool,
  userPoolClient: auth.userPoolClient,
  bus: events.bus,
  emailQueue: events.emailQueue,
  guardrailId: ai.guardrailId,
  guardrailVersion: ai.guardrailVersion,
});
new CostStack(app, `${prefix}-cost`, { env });

cdk.Tags.of(app).add('project', 'hivemate-ai');
cdk.Tags.of(app).add('stage', stage);
void api;
