import * as cdk from 'aws-cdk-lib';
import * as cognito from 'aws-cdk-lib/aws-cognito';
import * as dynamodb from 'aws-cdk-lib/aws-dynamodb';
import * as iam from 'aws-cdk-lib/aws-iam';
import * as lambda from 'aws-cdk-lib/aws-lambda';
import * as path from 'path';
import { Construct } from 'constructs';

interface AuthStackProps extends cdk.StackProps {
  table: dynamodb.ITable;
}

export class AuthStack extends cdk.Stack {
  readonly userPool: cognito.UserPool;
  readonly userPoolClient: cognito.UserPoolClient;

  constructor(scope: Construct, id: string, props: AuthStackProps) {
    super(scope, id, props);

    // Creates the tenant and stamps custom:tenantId on the new user.
    const postConfirmation = new lambda.Function(this, 'PostConfirmation', {
      runtime: lambda.Runtime.PYTHON_3_13,
      handler: 'src.auth.post_confirmation.handler',
      code: lambda.Code.fromAsset(path.join(__dirname, '../../services'), { exclude: ['tests', '**/__pycache__'] }),
      timeout: cdk.Duration.seconds(15),
      environment: { TABLE_NAME: props.table.tableName },
    });
    props.table.grantWriteData(postConfirmation);
    postConfirmation.addToRolePolicy(new iam.PolicyStatement({
      actions: ['cognito-idp:AdminUpdateUserAttributes'],
      // Wildcard avoids a circular dependency (pool -> trigger -> pool).
      resources: [`arn:aws:cognito-idp:${this.region}:${this.account}:userpool/*`],
    }));

    this.userPool = new cognito.UserPool(this, 'UserPool', {
      selfSignUpEnabled: true,
      signInAliases: { email: true },
      autoVerify: { email: true },
      standardAttributes: { email: { required: true, mutable: false } },
      customAttributes: {
        tenantId: new cognito.StringAttribute({ mutable: true }),
        role: new cognito.StringAttribute({ mutable: true }),
        businessName: new cognito.StringAttribute({ mutable: false, maxLen: 100 }),
      },
      passwordPolicy: { minLength: 12, requireSymbols: true, requireDigits: true },
      accountRecovery: cognito.AccountRecovery.EMAIL_ONLY,
      lambdaTriggers: { postConfirmation },
      removalPolicy: cdk.RemovalPolicy.DESTROY,
    });

    // Operators (not businesses) belong here. Only an AWS admin can add a user (AdminAddUserToGroup); no browser path exists.
    new cognito.CfnUserPoolGroup(this, 'PlatformAdmins', {
      userPoolId: this.userPool.userPoolId, groupName: 'platform-admins', description: 'Hivemate operators: read-only view across businesses',
    });

    this.userPoolClient = this.userPool.addClient('WebClient', {
      authFlows: { userSrp: true },
      generateSecret: false,
      // The browser must never be able to set its own tenant or role.
      writeAttributes: new cognito.ClientAttributes().withStandardAttributes({ email: true })
        .withCustomAttributes('businessName'),
      readAttributes: new cognito.ClientAttributes().withStandardAttributes({ email: true })
        .withCustomAttributes('tenantId', 'role', 'businessName'),
    });

    new cdk.CfnOutput(this, 'UserPoolId', { value: this.userPool.userPoolId });
    new cdk.CfnOutput(this, 'UserPoolClientId', { value: this.userPoolClient.userPoolClientId });
  }
}
