# Go-live checklist: what only you can do

The code for Hivemate 2.0 is built and tested against fakes. These steps need your accounts, a real device or a third party, so they cannot be done from the repo.
**Deployed to `hivemate-dev` on 2026-11-15** (backend and dashboard). Verified live that day:
- `tests/e2e/v2_e2e.py`: 31/31 (packs, policy safety rules, chat and email becoming deals, unified inbox, approve-and-send, impact from events, Ask, Customer 360, connections, cross-tenant isolation).
- `tests/e2e/agent_e2e.py`: 37/38. The one miss is a strict string check on the model's wording (it answered the opening time without repeating the closing time), not a functional failure.
- Public endpoints: bad webhook signature 401, Microsoft validation handshake echoes the token, forged OAuth state is refused, every new route returns 401 without a token. The scheduled worker ran cleanly.

**Update 2026-11-16:** PR #1 merged to `main`; backend and dashboard redeployed from `main`. Re-verified live after that deploy:
- `tests/e2e/v2_e2e.py` 31/31 again, and `tests/e2e/public_chat_e2e.py` 25/25 (public chat, including the per-visitor and per-business rate limits).
- The scheduled worker ran 67 times in 24 hours with no errors. It created no follow-ups, because no real enquiry has arrived since the deploy: a follow-up firing on real data is still unobserved.
- The dashboard was redesigned (sidebar navigation, graphical overview, pipeline board) and checked on desktop and at phone width on a local build with seeded data. It has not been checked on the live site with a real sign-in or on a physical phone.

Still NOT verified, and only you can do it: everything in sections 2 to 4 below.

## 1. Deploy (done for dev; repeat after changes)
Use the `hivemate` AWS profile. If your shell has `AWS_ACCESS_KEY_ID` set for another project, unset it first or CDK deploys as the wrong user.
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
