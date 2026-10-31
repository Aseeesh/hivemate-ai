import * as cdk from 'aws-cdk-lib';
import * as bedrock from 'aws-cdk-lib/aws-bedrock';
import * as kms from 'aws-cdk-lib/aws-kms';
import * as s3 from 'aws-cdk-lib/aws-s3';
import { Construct } from 'constructs';

interface AiStackProps extends cdk.StackProps {
  docsBucket: s3.IBucket;
  dataKey: kms.IKey;
}

/**
 * Shared Bedrock Guardrail applied to every model call.
 * (Bedrock Knowledge Base is added in Phase 4 - see docs/ROADMAP.md.)
 */
export class AiStack extends cdk.Stack {
  readonly guardrailId: string;
  readonly guardrailVersion: string;

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
  }
}
