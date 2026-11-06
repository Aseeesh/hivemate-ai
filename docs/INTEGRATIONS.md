# Fitting Hivemate into a business that already runs

Hivemate is an extra pair of hands, not a replacement. Nothing the business uses today is switched off, moved or re-routed.

| Their system | What stays | What Hivemate adds |
|---|---|---|
| **Website** (WordPress, Wix, Shopify, Squarespace, hand-built, Next.js) | Their site, forms, phone number | One `<script>` line (paste it in the site footer or Google Tag Manager). A chat bubble that answers from their own documents. Optional `data-whatsapp="64…"` adds a "Continue on WhatsApp" link to their own number. If the script fails to load, nothing on the site changes. |
| **Gmail** | Their inbox, their address, how they reply | A Google Apps Script in **their own Google account** leaves a suggested reply in Gmail **Drafts**. They read, edit and press Send. Nothing is sent for them. Complaints, refunds and prices are labelled `Hivemate-needs-you` with no draft. |
| **WhatsApp** | Their WhatsApp number and the app they already use | The assistant answers on that number **outside opening hours only** (default), or always. During opening hours it stays silent and the owner answers as usual. |

## Website
Dashboard → Customers → "Add the chat to your website". Lock it to their domain(s). Add their WhatsApp number to get the handoff link.
The widget builds its markup with `textContent` only and loads asynchronously.

## Gmail (draft-first, no Google app review)
Dashboard → Emails → "Gmail replies, in your own Gmail" → Create my key. Paste the generated script into script.google.com signed in as the
business's Gmail, press Run once to authorise, then add a time trigger (every 10 minutes).
- The key can only ask for suggested replies for that one business. It cannot read data or send mail. Only its hash is stored; "Create a new key" replaces it and "Disconnect" removes it.
- Suggestions use the business's **customer-visible** documents only, and are capped at 200 a day.
- Why not "Sign in with Google" for everyone: creating drafts needs Google's restricted Gmail scopes, which require an app security review for a public app. The Apps Script route runs under the owner's own consent, so it needs none. Revisit that when there are many businesses.
- Not covered: Outlook, and Gmail on a phone only (the script runs in the cloud, so the phone still shows the drafts).

## WhatsApp
Replies go through AWS End User Messaging Social (the business's WhatsApp Business Account linked in the AWS console). In the dashboard,
Customers → "Connect a WhatsApp number": choose *Only outside my opening hours* or *Always*.
- **Keeping the existing WhatsApp Business app on the same number:** Meta's "coexistence" feature is reported to allow this (one number on the app and the API together, set up through Embedded Signup), but regional availability and AWS support for it must be confirmed with Meta/AWS for New Zealand before promising it. Until then the safe path is the website's "Continue on WhatsApp" link, which uses their normal WhatsApp.
- A person taking over: mark the conversation as handed off in the dashboard and the assistant stays quiet until it is handed back.
- Not built: detecting that the owner replied from their own app (needs Meta's message-echo webhook).

## Honest limits
- The Gmail script and the WhatsApp number need the owner's own Google and Meta accounts, which only they can authorise.
- Quiet-hours mode is Monday to Friday with one start and end time.
