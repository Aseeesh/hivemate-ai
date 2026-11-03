'use client';
import { Fragment, useCallback, useEffect, useRef, useState, type FormEvent } from 'react';
import { api, type ChatReply, type Conv, type ConvDetail, type Lead } from '@/lib/api';

const tone = (s: string) => (s === 'COMPLETE' ? 'ok' : s === 'HANDOFF' ? 'hold' : '');

function TestChat({ onTurn }: { onTurn: () => void }) {
  const [log, setLog] = useState<{ who: 'you' | 'agent'; text: string }[]>([]);
  const [cid, setCid] = useState<string>(); const [text, setText] = useState(''); const [busy, setBusy] = useState(false);
  const [info, setInfo] = useState<ChatReply>(); const [error, setError] = useState('');
  const end = useRef<HTMLDivElement>(null);
  useEffect(() => { end.current?.scrollIntoView({ block: 'nearest' }); }, [log]);

  async function send(e: FormEvent) {
    e.preventDefault(); const t = text.trim(); if (!t) return;
    setBusy(true); setError(''); setText(''); setLog((l) => [...l, { who: 'you', text: t }]);
    try {
      const r = await api<ChatReply>('POST', '/chat', { message: t, conversationId: cid });
      setCid(r.conversationId); setInfo(r); setLog((l) => [...l, { who: 'agent', text: r.reply || '(the team has taken over this conversation)' }]); onTurn();
    } catch (err) { setError((err as Error).message); } finally { setBusy(false); }
  }
  return (
    <section className="card stack">
      <div className="row" style={{ justifyContent: 'space-between' }}>
        <h2>Try your agent</h2>
        <button className="btn" onClick={() => { setLog([]); setCid(undefined); setInfo(undefined); }}>New conversation</button>
      </div>
      <p className="muted">Chat as a customer would. Needs the Conversation Agent plugin installed (Plugins tab) and documents synced.</p>
      <div style={{ minHeight: 160, maxHeight: 320, overflowY: 'auto' }} className="stack" aria-live="polite">
        {log.map((m, i) => (
          <div key={i} style={{ justifySelf: m.who === 'you' ? 'end' : 'start', maxWidth: '85%', padding: '8px 12px', borderRadius: 12, background: m.who === 'you' ? 'var(--fern)' : 'var(--bg)', color: m.who === 'you' ? '#fff' : 'inherit', border: '1px solid var(--line)' }}>{m.text}</div>
        ))}
        {busy && <div className="muted">Typing…</div>}<div ref={end} />
      </div>
      {error && <p className="err" role="alert">{error}</p>}
      <form className="row" onSubmit={send}>
        <input style={{ flex: 1, minWidth: 200 }} value={text} onChange={(e) => setText(e.target.value)} placeholder="Type a customer message" aria-label="Customer message" maxLength={1500} />
        <button className="btn primary" disabled={busy}>Send</button>
      </form>
      {info && <div className="row"><span className={`tag ${tone(info.complete ? 'COMPLETE' : info.status)}`}>{info.complete ? 'lead complete' : info.status}</span>
        {Object.entries(info.collected).map(([k, v]) => <span key={k} className="tag">{k}: {v}</span>)}</div>}
    </section>
  );
}

function Transcript({ id, isAdmin, onChange }: { id: string; isAdmin: boolean; onChange: () => void }) {
  const [d, setD] = useState<ConvDetail>(); const [err, setErr] = useState('');
  const load = useCallback(() => api<ConvDetail>('GET', `/conversations/${id}`).then(setD).catch((e: Error) => setErr(e.message)), [id]);
  useEffect(() => { load(); }, [load]);
  async function setStatus(status: 'OPEN' | 'CLOSED') { await api('POST', `/conversations/${id}/status`, { status }); await load(); onChange(); }
  if (err) return <p className="err">{err}</p>;
  if (!d) return <p className="muted">Loading…</p>;
  return (
    <div className="stack" style={{ marginTop: 10 }}>
      {d.turns.map((t, i) => <div key={i}><span className="muted mono">{t.role === 'user' ? 'Customer' : 'Agent'}</span><blockquote>{t.text}</blockquote></div>)}
      {isAdmin && <div className="row">
        {d.conversation.status !== 'OPEN' && <button className="btn primary" onClick={() => setStatus('OPEN')}>Give back to the agent</button>}
        {d.conversation.status !== 'CLOSED' && <button className="btn" onClick={() => setStatus('CLOSED')}>Close</button>}
      </div>}
    </div>
  );
}

function WhatsAppLink() {
  const [meta, setMeta] = useState(''); const [orig, setOrig] = useState(''); const [msg, setMsg] = useState('');
  async function link(e: FormEvent) {
    e.preventDefault(); setMsg('');
    try { await api('PUT', '/channels/whatsapp', { metaPhoneNumberId: meta, originationPhoneNumberId: orig }); setMsg('Linked.'); } catch (err) { setMsg((err as Error).message); }
  }
  return (
    <details className="card"><summary>Connect a WhatsApp number</summary>
      <form className="stack" onSubmit={link} style={{ marginTop: 12 }}>
        <p className="muted">After registering your number in AWS End User Messaging Social, enter its two IDs. Customer messages to that number will be answered by this agent.</p>
        <label>Meta phone number ID (digits)<input required pattern="\d{5,30}" value={meta} onChange={(e) => setMeta(e.target.value)} /></label>
        <label>AWS phone number ID (phone-number-id-…)<input required value={orig} onChange={(e) => setOrig(e.target.value)} /></label>
        <div className="row"><button className="btn primary">Link number</button><span role="status" className="muted">{msg}</span></div>
      </form>
    </details>
  );
}

function WebChannel() {
  const [key, setKey] = useState<string | null>(); const [origins, setOrigins] = useState(''); const [msg, setMsg] = useState('');
  const publicUrl = process.env.NEXT_PUBLIC_PUBLIC_CHAT_URL ?? '';
  useEffect(() => {
    api<{ key: string | null; allowedOrigins: string[] }>('GET', '/channels/web').then((c) => { setKey(c.key); setOrigins(c.allowedOrigins.join('\n')); }).catch(() => undefined);
  }, []);
  async function save(rotate: boolean) {
    setMsg('');
    try {
      const list = origins.split(/\s+/).filter(Boolean);
      const c = await api<{ key: string }>('PUT', '/channels/web', { allowedOrigins: list, rotate });
      setKey(c.key); setMsg(rotate ? 'New key created. The old one stopped working.' : 'Saved.');
    } catch (err) { setMsg((err as Error).message); }
  }
  const snippet = key ? `<script src="${publicUrl}/widget.js" data-key="${key}" async></script>` : '';
  return (
    <details className="card"><summary>Add the chat to your website</summary>
      <div className="stack" style={{ marginTop: 12 }}>
        <p className="muted">Paste one line into your site. Visitors chat with this agent without signing in; leads show up below. Limit it to your own site so others can&apos;t embed it.</p>
        <label>Allowed websites (one per line, e.g. https://sparkclean.co.nz; leave empty to allow any)
          <textarea rows={3} value={origins} onChange={(e) => setOrigins(e.target.value)} />
        </label>
        <div className="row">
          <button className="btn primary" onClick={() => save(false)}>{key ? 'Save' : 'Create embed code'}</button>
          {key && <button className="btn" onClick={() => save(true)}>Rotate key</button>}
          <span role="status" className="muted">{msg}</span>
        </div>
        {key && <><label>Embed code<input readOnly value={snippet} onFocus={(e) => e.currentTarget.select()} /></label>
          {!publicUrl && <p className="muted">Set NEXT_PUBLIC_PUBLIC_CHAT_URL in web/.env.local to the PublicChatUrl stack output.</p>}</>}
      </div>
    </details>
  );
}

export default function Agent({ isAdmin }: { isAdmin: boolean }) {
  const [leads, setLeads] = useState<Lead[]>([]); const [convs, setConvs] = useState<Conv[]>([]); const [open, setOpen] = useState<string>();
  const load = useCallback(() => {
    api<Lead[]>('GET', '/leads').then(setLeads).catch(() => undefined);
    api<Conv[]>('GET', '/conversations').then(setConvs).catch(() => undefined);
  }, []);
  useEffect(() => { load(); const t = setInterval(load, 8000); return () => clearInterval(t); }, [load]);

  return (
    <div className="stack">
      <TestChat onTurn={load} />
      {isAdmin && <WebChannel />}
      {isAdmin && <WhatsAppLink />}
      <section className="stack">
        <h2>Leads</h2>
        {!leads.length && <p className="muted">No leads yet.</p>}
        {leads.map((l) => (
          <article key={l.SK} className="card stack">
            <div className="row" style={{ justifyContent: 'space-between' }}>
              <h3>{l.collected.name ?? 'Unknown customer'}{l.collected.need ? ` · ${l.collected.need}` : ''}</h3>
              <div className="row"><span className="tag">{l.channel}</span><span className={`tag ${tone(l.status)}`}>{l.status}</span></div>
            </div>
            <div className="row">{Object.entries(l.collected).map(([k, v]) => <span key={k} className="tag">{k.replace(/_/g, ' ')}: {v}</span>)}</div>
            {l.handoffReason && <p className="err">Needs a person: {l.handoffReason}</p>}
            {l.summary && <p className="muted"><strong>AI summary</strong> (can contain mistakes; the details above are what the customer said): {l.summary}</p>}
          </article>
        ))}
      </section>
      <section className="card">
        <h2>Conversations</h2>
        <table><thead><tr><th>Customer</th><th>Channel</th><th>Status</th><th>Messages</th><th /></tr></thead><tbody>
          {convs.map((c) => (
            <Fragment key={c.convId}>
              <tr><td className="mono">{c.collected.name ?? c.customer}</td><td>{c.channel}</td><td><span className={`tag ${tone(c.status)}`}>{c.status}</span></td><td>{c.turns}</td>
                <td>{isAdmin && <button className="btn" onClick={() => setOpen(open === c.convId ? undefined : c.convId)}>{open === c.convId ? 'Hide' : 'Open'}</button>}</td></tr>
              {open === c.convId && <tr><td colSpan={5}><Transcript id={c.convId} isAdmin={isAdmin} onChange={load} /></td></tr>}
            </Fragment>
          ))}
          {!convs.length && <tr><td colSpan={5} className="muted">No conversations yet.</td></tr>}
        </tbody></table>
      </section>
    </div>
  );
}
