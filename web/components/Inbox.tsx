'use client';
import { useCallback, useEffect, useState, type FormEvent } from 'react';
import { api, type Message } from '@/lib/api';

const tone = (s: string) => (s === 'PENDING_APPROVAL' ? 'hold' : s === 'REJECTED' ? 'bad' : 'ok');

export default function Inbox() {
  const [msgs, setMsgs] = useState<Message[]>([]); const [msg, setMsg] = useState(''); const [busy, setBusy] = useState(false);
  const [from, setFrom] = useState('customer@example.com'); const [subject, setSubject] = useState('Opening hours'); const [body, setBody] = useState('What time do you open on Saturday?');
  const load = useCallback(() => api<Message[]>('GET', '/messages').then(setMsgs).catch((e: Error) => setMsg(e.message)), []);
  useEffect(() => { load(); const t = setInterval(load, 5000); return () => clearInterval(t); }, [load]);

  async function decide(m: Message, action: 'approve' | 'reject') {
    setBusy(true); try { await api('POST', `/messages/${m.SK.replace('MSG#', '')}/${action}`); await load(); } catch (e) { setMsg((e as Error).message); } finally { setBusy(false); }
  }
  async function send(e: FormEvent) {
    e.preventDefault(); setBusy(true); setMsg('');
    try { await api('POST', '/plugins/email-automation/ingest', { from, subject, body }); setMsg('Sent. The AI draft appears in a few seconds.'); }
    catch (err) { setMsg((err as Error).message); } finally { setBusy(false); }
  }

  return (
    <div className="stack">
      <details className="card"><summary>Send a test email to this business</summary>
        <form className="stack" onSubmit={send} style={{ marginTop: 12 }}>
          <label>From<input type="email" required value={from} onChange={(e) => setFrom(e.target.value)} /></label>
          <label>Subject<input required value={subject} onChange={(e) => setSubject(e.target.value)} /></label>
          <label>Message<textarea required rows={3} value={body} onChange={(e) => setBody(e.target.value)} /></label>
          <div className="row"><button className="btn primary" disabled={busy}>Send test email</button><span role="status" className="muted">{msg}</span></div>
          <p className="muted">Needs the Email Automation plugin installed. Real inbound mail arrives with SES later.</p>
        </form>
      </details>
      {!msgs.length && <p className="muted">No messages yet.</p>}
      {msgs.map((m) => (
        <article key={m.SK} className="card stack">
          <div className="row" style={{ justifyContent: 'space-between' }}>
            <h3>{m.subject || '(no subject)'}</h3>
            <div className="row"><span className="tag">{m.category} · {Math.round(m.confidence * 100)}%</span><span className={`tag ${tone(m.status)}`}>{m.status}</span></div>
          </div>
          <span className="muted">From {m.from}</span>
          <p>{m.body}</p>
          <div><strong>AI draft</strong><blockquote>{m.draftReply || <em className="muted">No draft produced. Reply manually.</em>}</blockquote></div>
          {m.status === 'PENDING_APPROVAL' && <div className="row">
            <button className="btn primary" disabled={busy} onClick={() => decide(m, 'approve')}>Approve and send</button>
            <button className="btn danger" disabled={busy} onClick={() => decide(m, 'reject')}>Reject</button>
          </div>}
        </article>
      ))}
    </div>
  );
}
