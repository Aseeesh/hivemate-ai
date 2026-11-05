/** Static export: the dashboard is fully client-side (Cognito + fetch), so it can be hosted on S3/CloudFront. */
/** @type {import('next').NextConfig} */
export default { reactStrictMode: true, output: 'export', trailingSlash: true };
