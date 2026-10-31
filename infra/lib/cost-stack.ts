import * as cdk from 'aws-cdk-lib';
import * as budgets from 'aws-cdk-lib/aws-budgets';
import { Construct } from 'constructs';

/** Budgets are alerts, not hard caps - still the first thing to deploy. */
export class CostStack extends cdk.Stack {
  constructor(scope: Construct, id: string, props: cdk.StackProps) {
    super(scope, id, props);
    const limit = Number(this.node.tryGetContext('monthlyBudgetUsd'));
    const email = this.node.tryGetContext('alertEmail') as string;
    if (!email) throw new Error('Pass -c alertEmail=you@example.com (CI: ALERT_EMAIL variable)');

    new budgets.CfnBudget(this, 'MonthlyBudget', {
      budget: {
        budgetName: 'hivemate-monthly',
        budgetType: 'COST',
        timeUnit: 'MONTHLY',
        budgetLimit: { amount: limit, unit: 'USD' },
      },
      notificationsWithSubscribers: [50, 80, 100].map((pct) => ({
        notification: {
          notificationType: 'ACTUAL',
          comparisonOperator: 'GREATER_THAN',
          threshold: pct,
          thresholdType: 'PERCENTAGE',
        },
        subscribers: [{ subscriptionType: 'EMAIL', address: email }],
      })),
    });
  }
}
