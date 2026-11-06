/** The Google Apps Script the owner pastes into their own Google account. It only creates Gmail DRAFTS; it never sends. */
export const gmailScript = (url: string, token: string) => `// Hivemate: suggests replies to customer enquiries as Gmail DRAFTS in your own Gmail. It never sends anything.
// After pasting: press Run once to authorise, then Triggers > Add trigger > run > Time-driven > every 10 minutes.
const HIVEMATE_URL = '${url}/integrations/email/suggest';
const HIVEMATE_TOKEN = '${token}';
const SEARCH = 'in:inbox is:unread newer_than:2d -from:me -category:promotions -category:social -category:updates -label:Hivemate-handled';

function label(name) { return GmailApp.getUserLabelByName(name) || GmailApp.createLabel(name); }

function run() {
  const handled = label('Hivemate-handled'), ready = label('Hivemate-draft-ready'), needsYou = label('Hivemate-needs-you');
  GmailApp.search(SEARCH, 0, 10).forEach(function (thread) {
    const msgs = thread.getMessages(), msg = msgs[msgs.length - 1], from = msg.getFrom();
    if (/no-?reply|donotreply|mailer-daemon/i.test(from)) { thread.addLabel(handled); return; }
    const res = UrlFetchApp.fetch(HIVEMATE_URL, {
      method: 'post', contentType: 'application/json', muteHttpExceptions: true,
      headers: { Authorization: 'Bearer ' + HIVEMATE_TOKEN },
      payload: JSON.stringify({ from: from, subject: msg.getSubject(), body: msg.getPlainBody().slice(0, 6000) }),
    });
    if (res.getResponseCode() !== 200) return; // try again on the next run
    const out = JSON.parse(res.getContentText());
    if (out.needsHuman || !out.reply) { thread.addLabel(needsYou); }
    else { msg.createDraftReply(out.reply); thread.addLabel(ready); }
    thread.addLabel(handled);
  });
}
`;
