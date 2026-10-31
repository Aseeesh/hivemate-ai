import * as cdk from 'aws-cdk-lib';
import * as events from 'aws-cdk-lib/aws-events';
import * as targets from 'aws-cdk-lib/aws-events-targets';
import * as sqs from 'aws-cdk-lib/aws-sqs';
import * as cloudwatch from 'aws-cdk-lib/aws-cloudwatch';
import { Construct } from 'constructs';

/** Event backbone: plugins subscribe to event types through EventBridge rules. */
export class EventsStack extends cdk.Stack {
  readonly bus: events.EventBus;
  readonly emailQueue: sqs.Queue;
  readonly emailDlq: sqs.Queue;

  constructor(scope: Construct, id: string, props: cdk.StackProps) {
    super(scope, id, props);

    this.bus = new events.EventBus(this, 'Bus', { eventBusName: 'hivemate' });

    this.emailDlq = new sqs.Queue(this, 'EmailDlq', { retentionPeriod: cdk.Duration.days(14) });
    this.emailQueue = new sqs.Queue(this, 'EmailQueue', {
      visibilityTimeout: cdk.Duration.seconds(120), // > processor Lambda timeout
      deadLetterQueue: { queue: this.emailDlq, maxReceiveCount: 3 },
    });

    // Manifest "events": ["email.received"] becomes this rule.
    new events.Rule(this, 'EmailReceivedRule', {
      eventBus: this.bus,
      eventPattern: { source: ['hivemate.channel'], detailType: ['email.received'] },
      targets: [new targets.SqsQueue(this.emailQueue)],
    });

    // Archive for replay while debugging failed workflows.
    new events.Archive(this, 'Archive', {
      sourceEventBus: this.bus,
      eventPattern: { source: ['hivemate.channel'] },
      retention: cdk.Duration.days(7),
    });

    new cloudwatch.Alarm(this, 'DlqAlarm', {
      metric: this.emailDlq.metricApproximateNumberOfMessagesVisible(),
      threshold: 1,
      evaluationPeriods: 1,
      alarmDescription: 'Email processing messages landed in the DLQ',
    });
  }
}
