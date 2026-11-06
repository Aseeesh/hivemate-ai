'use client';
import { useEffect, useRef, useState, type FormEvent } from 'react';

/* Customer-facing chat page. No sign-in, no dashboard: it only talks to the public chat API with a site key.
   Share the link (/chat/?key=pk_...) on social profiles, in emails, on invoices, or as a QR code. Replies are rendered as plain text. */

const API = process.env.NEXT_PUBLIC_PUBLIC_CHAT_URL ?? '';
type Msg = { who: 'me' | 'bot'; text: string };
type Info = { agentName: string; business: string; suggestions?: string[] };

export default function CustomerChat() {
  const [key, setKey] = useState(''); const [info, setInfo] = useState<Info>(); const [off, setOff] = useState(false);
  const [log, setLog] = useState<Msg[]>([]); const [text, setText] = useState(''); const [busy, setBusy] = useState(false);
  const [cid, setCid] = useState<string | null>(null); const [sent, setSent] = useState(false);
  const end = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const k = new URLSearchParams(window.location.search).get('key') ?? '';
    setKey(k);
    try { setCid(sessionStorage.getItem(`hm:${k}`)); } catch { /* private mode: the chat still works, it just will not resume */ }
    if (!k || !API) { setOff(true); return; }
    fetch(`${API}/info?key=${encodeURIComponent(k)}`).then(async (r) => { if (!r.ok) throw new Error(); setInfo(await r.json()); }).catch(() => setOff(true));
  }, []);
  useEffect(() => { if (info && !log.length) setLog([{ who: 'bot', text: `Hi! I'm ${info.agentName}, the assistant for ${info.business}. Ask me anything about our services, prices and areas.` }]); }, [info, log.length]);
  useEffect(() => { end.current?.scrollIntoView({ block: 'end', behavior: 'smooth' }); }, [log, busy]);

  async function say(t: string) {
    t = t.trim(); if (!t || busy) return;
    setSent(true); setBusy(true); setText(''); setLog((l) => [...l, { who: 'me', text: t }]);
    try {
      const r = await fetch(`${API}/chat`, { method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify({ key, message: t, conversationId: cid }) });
      const j = await r.json();
      if (r.ok) { setCid(j.conversationId); try { sessionStorage.setItem(`hm:${key}`, j.conversationId); } catch { /* ignore */ } if (j.reply) setLog((l) => [...l, { who: 'bot', text: j.reply }]); }
      else setLog((l) => [...l, { who: 'bot', text: j.error || 'Something went wrong. Please try again.' }]);
    } catch { setLog((l) => [...l, { who: 'bot', text: 'Network problem. Please try again.' }]); } finally { setBusy(false); }
  }
  const submit = (e: FormEvent) => { e.preventDefault(); void say(text); };

  if (off) return <main className="cc-wrap"><div className="cc-card"><h1>Chat is not available</h1><p className="muted">This link is not active. Please contact the business directly.</p></div></main>;
  return (
    <main className="cc-wrap">
      <div className="cc-card">
        <header className="cc-head"><span className="cc-dot" aria-hidden />
          <div><strong>{info ? info.business : 'Loading…'}</strong><div className="cc-sub">Chat with {info?.agentName ?? 'us'}, our AI assistant</div></div></header>
        <div className="cc-log" aria-live="polite">
          {log.map((m, i) => <div key={i} className={`cc-msg ${m.who}`}>{m.text}</div>)}
          {busy && <div className="cc-msg bot cc-typing" aria-label="Typing"><i /><i /><i /></div>}
          <div ref={end} />
        </div>
        {!sent && info && <div className="cc-chips">{(info.suggestions ?? []).map((s) => <button key={s} onClick={() => say(s)}>{s}</button>)}</div>}
        <form className="cc-form" onSubmit={submit}>
          <input value={text} onChange={(e) => setText(e.target.value)} placeholder="Type your message" aria-label="Your message" maxLength={800} disabled={!info} />
          <button disabled={busy || !info}>Send</button>
        </form>
        <footer className="cc-foot"><button className="linklike" onClick={() => say('I would like to speak to a person please')} disabled={busy || !info}>Talk to a person</button><span>AI assistant: it can make mistakes, the team may follow up.</span></footer>
      </div>
    </main>
  );
}
