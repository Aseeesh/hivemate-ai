import { Construct } from 'constructs';

/** Hosted dashboard origin(s), passed as `-c webOrigin=https://xxxx.cloudfront.net` (the SiteUrl output of the web stack). */
export function webOrigins(scope: Construct): string[] {
  const v = scope.node.tryGetContext('webOrigin') as string | undefined;
  return v && /^https:\/\/[a-z0-9.-]+$/.test(v) ? [v] : [];
}
