'use client';
import { useCallback, useEffect, useState } from 'react';
import { api, type ConvDetail, type InboxRow } from '@/lib/api';

const STAGES: [string, string][] = [['quote_sent', 'Quote sent'], ['won', 'Won'], ['lost', 'Lost']];
const ago = (t: number) => { if (!t) return ''; const m = Math.max(1, Math.round((Date.now() / 1000 - t) / 60)); return m < 60 ? `${m} min ago` : m < 1440 ? `${Math.round(m / 60)} h ago` : `${Math.round(m / 1440)} d ago`; };

export default function UnifiedInbox({ isAdmin }: { isAdmin: boolean }) {
  const [rows, setRows] = useState<InboxRow[] | null>(null); const [members, setMembers] = useState<string[]>([]);
  const [channel, setChannel] = useState(''); const [status, setStatus] = useState(''); const [assignee, setAssignee] = useState('');
  const [open, setOpen] = useState(''); const [detail, setDetail] = useState<ConvDetail | null>(null); const [msg, setMsg] = useState('');
  const load = useCallback(() => {
    const q = new URLSearchParams({ ...(channel ? { channel } : {}), ...(status ? { status } : {}), ...(assignee ? { assignee } : {}) });
    return api<{ items: InboxRow[] }>('GET', `/inbox?${q}`).then((r) => setRows(r.items)).catch((e: Error) => setMsg(e.message));
  }, [channel, status, assignee]);
  useEffect(() => { load(); const t = setInterval(load, 15000); return () => clearInterval(t); }, [load]);
  useEffect(() => { api<{ members: string[] }>('GET', '/team').then((r) => setMembers(r.members)).catch(() => undefined); }, []);

  async function openRow(r: InboxRow) {
    const k = `${r.kind}:${r.id}`; setDetail(null);
    if (open === k) return setOpen('');
    setOpen(k);
    if (r.kind === 'conversation' && isAdmin) api<ConvDetail>('GET', `/conversations/${r.id}`).then(setDetail).catch((e: Error) => setMsg(e.message));
  }
  async function deal(r: InboxRow, what: 'stage' | 'assign', body: Record<string, string>) {
    setMsg('');
    try { await api('POST', `/deals/${r.dealId}/${what}`, body); await load(); } catch (e) { setMsg((e as Error).message); }
  }
  return (
    <div className="stack">
      <section className="card row" style={{ justifyContent: 'space-between' }} aria-label="Filters">
        <span className="muted">Every enquiry from email, your website chat and WhatsApp in one list.</span>
        <div className="row">
          <label className="row">Channel <select value={channel} onChange={(e) => setChannel(e.target.value)}><option value="">All</option>{['email', 'web', 'whatsapp'].map((c) => <option key={c}>{c}</option>)}</select></label>
          <label className="row">Show <select value={status} onChange={(e) => setStatus(e.target.value)}><option value="">Everything</option><option value="unanswered">Unanswered / needs you</option></select></label>
          <label className="row">Assigned to <select value={assignee} onChange={(e) => setAssignee(e.target.value)}><option value="">Anyone</option>{members.map((m) => <option key={m}>{m}</option>)}</select></label>
        </div>
      </section>
      {msg && <p className="err" role="alert">{msg}</p>}
      {rows && !rows.length && <p className="muted">No enquiries match.</p>}
      {rows?.map((r) => {
        const k = `${r.kind}:${r.id}`;
        return (
          <article key={k} className="card stack">
            <button className="btn" style={{ textAlign: 'left' }} aria-expanded={open === k} onClick={() => openRow(r)}>
              <span className="row" style={{ justifyContent: 'space-between' }}>
                <span><strong>{r.title}</strong> <span className="muted">{r.preview}</span></span>
                <span className="row"><span className="tag">{r.channel}</span>{r.category && <span className="tag">{r.category}</span>}
                  {r.unanswered && <span className="tag hold"><i className="pulse" />needs a reply</span>}
                  {r.stage && <span className="tag">{r.stage.replace('_', ' ')}</span>}<span className="muted">{ago(r.lastAt)}</span></span>
              </span>
            </button>
            {open === k && <div className="stack">
              {r.kind === 'conversation' && !isAdmin && <p className="muted">Only admins can read chat transcripts.</p>}
              {detail && detail.conversation.convId === r.id && detail.turns.map((t, i) => <div key={i} className={t.role === 'user' ? '' : 'muted'}><strong>{t.role === 'user' ? 'Customer' : 'Assistant'}:</strong> {t.text}</div>)}
              {r.kind === 'email' && <p className="muted">Open the Email drafts section to read the message and approve the reply.</p>}
              {r.dealId ? <div className="row">
                <label className="row">Assigned to <select value={r.assignee} onChange={(e) => deal(r, 'assign', { assignee: e.target.value })}><option value="">Nobody</option>{members.map((m) => <option key={m}>{m}</option>)}</select></label>
                {STAGES.map(([s, l]) => <button key={s} className="btn" aria-pressed={r.stage === s} onClick={() => deal(r, 'stage', { stage: s })}>Mark {l.toLowerCase()}</button>)}
              </div> : <p className="muted">Follow-up tracking starts once the customer shares a name, phone or email.</p>}
            </div>}
          </article>
        );
      })}
    </div>
  );
}
