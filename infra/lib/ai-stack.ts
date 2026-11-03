import * as cdk from 'aws-cdk-lib';
import * as bedrock from 'aws-cdk-lib/aws-bedrock';
import * as iam from 'aws-cdk-lib/aws-iam';
import * as kms from 'aws-cdk-lib/aws-kms';
import * as s3 from 'aws-cdk-lib/aws-s3';
import * as s3vectors from 'aws-cdk-lib/aws-s3vectors';
import { Construct } from 'constructs';

interface AiStackProps extends cdk.StackProps {
  docsBucket: s3.IBucket;
  dataKey: kms.IKey;
}

const EMBED_MODEL = 'amazon.titan-embed-text-v2:0';
const EMBED_DIMENSIONS = 1024;

/**
 * Shared AI infrastructure:
 *  - one Bedrock Guardrail applied to every model call
 *  - one Knowledge Base over the tenant docs bucket, vectors in S3 Vectors (serverless, no idle cost)
 *
 * Tenant isolation: every document has a sidecar `<file>.metadata.json` carrying `tenantId`,
 * and every Retrieve call filters on it (see services/src/plugins/email/processor.py).
 */
export class AiStack extends cdk.Stack {
  readonly guardrailId: string;
  readonly guardrailVersion: string;
  readonly knowledgeBaseId: string;
  readonly knowledgeBaseArn: string;
  readonly dataSourceId: string;

  constructor(scope: Construct, id: string, props: AiStackProps) {
    super(scope, id, props);

    const guardrail = new bedrock.CfnGuardrail(this, 'Guardrail', {
      name: 'hivemate-default',
      description: 'PII masking, prompt-attack and harmful content filters',
      blockedInputMessaging: 'Sorry, I cannot help with that request.',
      blockedOutputsMessaging: 'Sorry, I cannot provide that response.',
      contentPolicyConfig: {
        filtersConfig: [
          { type: 'PROMPT_ATTACK', inputStrength: 'HIGH', outputStrength: 'NONE' },
          { type: 'HATE', inputStrength: 'MEDIUM', outputStrength: 'MEDIUM' },
          { type: 'INSULTS', inputStrength: 'MEDIUM', outputStrength: 'MEDIUM' },
          { type: 'MISCONDUCT', inputStrength: 'MEDIUM', outputStrength: 'MEDIUM' },
        ],
      },
      sensitiveInformationPolicyConfig: {
        piiEntitiesConfig: [
          { type: 'CREDIT_DEBIT_CARD_NUMBER', action: 'BLOCK' },
          { type: 'PASSWORD', action: 'BLOCK' },
          { type: 'DRIVER_ID', action: 'ANONYMIZE' },
        ],
      },
    });
    const version = new bedrock.CfnGuardrailVersion(this, 'GuardrailV1', {
      guardrailIdentifier: guardrail.attrGuardrailId,
    });
    this.guardrailId = guardrail.attrGuardrailId;
    this.guardrailVersion = version.attrVersion;

    // ---- Vector store ----
    const vectorBucket = new s3vectors.CfnVectorBucket(this, 'VectorBucket', {});
    const index = new s3vectors.CfnIndex(this, 'VectorIndex', {
      vectorBucketArn: vectorBucket.attrVectorBucketArn,
      indexName: 'hivemate-docs',
      dataType: 'float32',
      dimension: EMBED_DIMENSIONS,
      distanceMetric: 'cosine',
      // Chunk text and source metadata exceed the 2KB filterable-metadata limit; only tenantId stays filterable.
      metadataConfiguration: { nonFilterableMetadataKeys: ['AMAZON_BEDROCK_TEXT', 'AMAZON_BEDROCK_METADATA'] },
    });

    // ---- Knowledge Base ----
    const kbRole = new iam.Role(this, 'KbRole', {
      assumedBy: new iam.ServicePrincipal('bedrock.amazonaws.com', {
        conditions: { StringEquals: { 'aws:SourceAccount': this.account } },
      }),
    });
    kbRole.addToPolicy(new iam.PolicyStatement({
      actions: ['bedrock:InvokeModel'],
      resources: [`arn:aws:bedrock:${this.region}::foundation-model/${EMBED_MODEL}`],
    }));
    kbRole.addToPolicy(new iam.PolicyStatement({
      actions: ['s3:GetObject', 's3:ListBucket'],
      resources: [props.docsBucket.bucketArn, props.docsBucket.arnForObjects('*')],
    }));
    // Identity-policy only: a key-policy grant would make the data stack depend on this one (cycle).
    kbRole.addToPolicy(new iam.PolicyStatement({
      actions: ['kms:Decrypt', 'kms:DescribeKey'],
      resources: [props.dataKey.keyArn],
    }));
    kbRole.addToPolicy(new iam.PolicyStatement({
      actions: ['s3vectors:*'],
      resources: [vectorBucket.attrVectorBucketArn, index.attrIndexArn],
    }));

    const kb = new bedrock.CfnKnowledgeBase(this, 'KnowledgeBase', {
      name: 'hivemate-docs',
      roleArn: kbRole.roleArn,
      knowledgeBaseConfiguration: {
        type: 'VECTOR',
        vectorKnowledgeBaseConfiguration: {
          embeddingModelArn: `arn:aws:bedrock:${this.region}::foundation-model/${EMBED_MODEL}`,
          embeddingModelConfiguration: {
            bedrockEmbeddingModelConfiguration: { dimensions: EMBED_DIMENSIONS, embeddingDataType: 'FLOAT32' },
          },
        },
      },
      storageConfiguration: {
        type: 'S3_VECTORS',
        s3VectorsConfiguration: { indexArn: index.attrIndexArn },
      },
    });
    kb.node.addDependency(kbRole);

    const ds = new bedrock.CfnDataSource(this, 'DocsSource', {
      name: 'tenant-docs',
      knowledgeBaseId: kb.attrKnowledgeBaseId,
      dataSourceConfiguration: {
        type: 'S3',
        s3Configuration: { bucketArn: props.docsBucket.bucketArn, inclusionPrefixes: ['tenants/'] },
      },
      dataDeletionPolicy: 'DELETE',
      vectorIngestionConfiguration: {
        chunkingConfiguration: {
          chunkingStrategy: 'FIXED_SIZE',
          fixedSizeChunkingConfiguration: { maxTokens: 300, overlapPercentage: 15 },
        },
      },
    });

    this.knowledgeBaseId = kb.attrKnowledgeBaseId;
    this.knowledgeBaseArn = kb.attrKnowledgeBaseArn;
    this.dataSourceId = ds.attrDataSourceId;

    new cdk.CfnOutput(this, 'KnowledgeBaseId', { value: this.knowledgeBaseId });
  }
}
