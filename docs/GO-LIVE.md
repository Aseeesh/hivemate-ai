# Go-live checklist: what only you can do

The code for Hivemate 2.0 is built and tested against fakes. These steps need your accounts, a real device or a third party, so they cannot be done from the repo.
Nothing below has been run for you. Tick each one only after you have seen it work.

## 1. Deploy
```bash
cd infra && npx cdk deploy --all -c stage=dev -c alertEmail=<you> -c senderEmail=<verified address>
cd ../web && npm run build && cd .. && ./scripts/deploy-web.sh   # existing script
```
The stack now adds: `SweeperFn` (every 15 minutes), `WebhooksFn`, a `<prefix>/apps` secret, and public routes `/oauth/{provider}/callback` and `/webhooks/{provider}` on the **public** API.

## 2. Register the OAuth apps (once per Hivemate deployment, not per customer)
Redirect URI for both: `<PublicChatUrl>/oauth/<provider>/callback` (the `PublicChatUrl` stack output; provider is `microsoft365` or `xero`).

**Microsoft 365** (Entra admin centre > App registrations, multi-tenant, web platform):
delegated permissions `offline_access`, `User.Read`, `Mail.ReadWrite`, `Mail.Send`. Create a client secret.
**Xero** (developer.xero.com > New app, web app): add the redirect URI, create a client secret, add a webhook for *Invoices* pointing to `<PublicChatUrl>/webhooks/xero` and copy its signing key.
Check the scope names in your Xero app: apps created after Xero's 2026 scope change use granular scopes. Override with `XERO_SCOPES` if needed.

Then store the settings (this secret is read by the Lambdas; it is never an environment variable):
```bash
aws secretsmanager put-secret-value --secret-id hivemate/dev/apps --secret-string '{
  "MS_CLIENT_ID":"...", "MS_CLIENT_SECRET":"...",
  "XERO_CLIENT_ID":"...", "XERO_CLIENT_SECRET":"...", "XERO_WEBHOOK_KEY":"..."
}'
```
Until this is done the Integrations tab says "not set up on this Hivemate yet" and nothing connects. Xero and Microsoft may require app verification before customers outside your own organisation can connect: check their current rules.

## 3. Prove each connection yourself before showing a customer
1. Integrations > Connect Microsoft 365 with a test mailbox. Send it an email. Within 15 minutes (or instantly if push notifications registered) a draft appears under Work Queue / Email drafts.
2. Approve it. Confirm the reply arrives **from the test mailbox** and is in its Sent Items.
3. Integrations > Connect Xero with the Demo Company. Create an overdue sales invoice. After the next sync a reminder task appears; approve it; confirm the email and the history note on the invoice.
4. Revoke the app in Microsoft/Xero. Within one sync the card shows "Needs reconnecting" and you get an email.

## 4. Other gaps (unchanged by this release)
| Gap | What to do |
|---|---|
| SES sandbox | Request production access in the SES console. Until then follow-ups only reach verified addresses and the "Sends that succeeded" figure will show failures. |
| WhatsApp | Link a real number and send real messages (docs/INTEGRATIONS.md). Unit-tested only. |
| Inbound email | Not configured. Outlook now covers inbound via the connector; Gmail uses the draft script. |
| Hosted dashboard auth | Sign up, confirm, sign in, let the token expire, sign in again, in a real browser. |
| Lambda concurrency | Service Quotas L-B99A9384. The worker runs 15-minutely and the API shares the account limit. |
| Website chat abuse test | Run `tests/e2e/public_chat_e2e.py`, then a burst test against the public API throttle. |
| Textract region | Confirm `AnalyzeExpense` is enabled in your region before relying on invoice reading. Multi-page PDFs are not supported (photos and one-page PDFs only). |

## 5. Alarms to watch
`SweeperErrors` (follow-ups and syncs stopped), the existing email DLQ alarm, and the connection cards in Integrations.
