#!/usr/bin/env bash
# Build the dashboard against the deployed backend and publish it to S3/CloudFront.
# Usage: AWS_PROFILE=hivemate scripts/deploy-web.sh [stage]   (default stage: dev)
set -euo pipefail
STAGE="${1:-dev}"; export AWS_REGION=ap-southeast-2 AWS_DEFAULT_REGION=ap-southeast-2
out() { aws cloudformation describe-stacks --stack-name "hivemate-$STAGE-$1" --query "Stacks[0].Outputs[?OutputKey=='$2'].OutputValue" --output text; }
export NEXT_PUBLIC_API_URL="$(out api ApiUrl)" NEXT_PUBLIC_PUBLIC_CHAT_URL="$(out api PublicChatUrl)"
export NEXT_PUBLIC_USER_POOL_ID="$(out auth UserPoolId)" NEXT_PUBLIC_USER_POOL_CLIENT_ID="$(out auth UserPoolClientId)"
BUCKET="$(out web SiteBucketName)"; DIST="$(out web DistributionId)"; URL="$(out web SiteUrl)"
(cd "$(dirname "$0")/../web" && npm ci --silent && npm run build)
OUT="$(dirname "$0")/../web/out"
# Hashed assets are immutable; HTML must revalidate so a new deploy shows up.
aws s3 sync "$OUT" "s3://$BUCKET" --delete --exclude "*.html" --cache-control "public,max-age=31536000,immutable" --only-show-errors
aws s3 sync "$OUT" "s3://$BUCKET" --exclude "*" --include "*.html" --cache-control "no-cache" --only-show-errors
aws cloudfront create-invalidation --distribution-id "$DIST" --paths "/*" --query Invalidation.Id --output text
echo "Published: $URL"
