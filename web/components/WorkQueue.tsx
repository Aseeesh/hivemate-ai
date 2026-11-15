'use client';
import { useCallback, useEffect, useState } from 'react';
import { api, type Task, type Work } from '@/lib/api';

const TYPE_LABEL: Record<string, string> = { follow_up: 'Follow-up', reply_overdue: 'Reply overdue', cold_lead: 'Gone cold', invoice_reminder: 'Invoice reminder', document_review: 'Document review', connection_attention: 'Connection', handoff: 'Needs a person' };
const WHY: Record<string, string> = {
  follow_up: 'The customer has not replied since our last message, and your follow-up timing says it is time to check in.',
  reply_overdue: 'The customer wrote and nobody has answered within your reply time.',
  cold_lead: 'The maximum number of follow-ups went out with no reply, so the lead is marked cold.',
  invoice_reminder: 'Xero shows this invoice unpaid past its due date. The wording gets firmer the longer it is overdue.',
  document_review: 'A document was read automatically. Check the figures before relying on them.',
  connection_attention: 'A connected system stopped working, so automations that use it are paused.',
};
const tone = (p: string) => (p === 'urgent' ? 'bad' : p === 'high' ? 'hold' : '');
const ago = (t: number) => { const m = Math.max(1, Math.round((Date.now() / 1000 - t) / 60)); return m < 60 ? `${m} min ago` : m < 1440 ? `${Math.round(m / 60)} h ago` : `${Math.round(m / 1440)} d ago`; };

export default function WorkQueue({ isAdmin, initialType = '', go }: { isAdmin: boolean; initialType?: string; go: (t: 'Integrations' | 'Customers' | 'Knowledge') => void }) {
  const [work, setWork] = useState<Work | null>(null); const [members, setMembers] = useState<string[]>([]);
  const [view, setView] = useState<'open' | 'done'>('open'); const [type, setType] = useState(initialType); const [channel, setChannel] = useState(''); const [assignee, setAssignee] = useState('');
  const [drafts, setDrafts] = useState<Record<string, string>>({}); const [open, setOpen] = useState<string>(''); const [msg, setMsg] = useState(''); const [isErr, setIsErr] = useState(false); const [busy, setBusy] = useState('');

  const load = useCallback(() => {
    const q = new URLSearchParams({ status: view, ...(type ? { type } : {}), ...(channel ? { channel } : {}), ...(assignee ? { assignee } : {}) });
    return api<Work>('GET', `/work?${q}`).then(setWork).catch((e: Error) => { setIsErr(true); setMsg(e.message); });
  }, [view, type, channel, assignee]);
  useEffect(() => { load(); const t = setInterval(load, 15000); return () => clearInterval(t); }, [load]);
  useEffect(() => { api<{ members: string[] }>('GET', '/team').then((r) => setMembers(r.members)).catch(() => undefined); }, []);

  async function act(t: Task, action: 'approve' | 'reject' | 'done' | 'snooze' | 'assign', body: Record<string, unknown> = {}, ok = '') {
    setBusy(t.taskId + action); setMsg(''); setIsErr(false);
    try { await api('POST', `/work/${t.taskId}/${action}`, body); setMsg(ok); await load(); } catch (e) { setIsErr(true); setMsg((e as Error).message); } finally { setBusy(''); }
  }
  const s = work?.summary;
  const types = Object.keys(TYPE_LABEL);

  return (
    <div className="stack">
      <section className="grid" aria-label="Queue summary" style={{ gridTemplateColumns: 'repeat(auto-fit,minmax(170px,1fr))' }}>
        {[{ n: s?.open ?? 0, l: 'Open', f: '' }, { n: s?.urgent ?? 0, l: 'Urgent', f: '' }, { n: s?.needsApproval ?? 0, l: 'Waiting for your approval', f: '' }, { n: s?.failed ?? 0, l: 'Failed, can be retried', f: '' }].map((k) => (
          <div key={k.l} className="card"><div className="hero-num">{k.n}</div><div>{k.l}</div></div>
        ))}
      </section>
      <section className="card row" aria-label="Filters" style={{ justifyContent: 'space-between' }}>
        <div className="row" role="group" aria-label="Show">
          <button className="btn" aria-pressed={view === 'open'} onClick={() => setView('open')}>To do</button>
          <button className="btn" aria-pressed={view === 'done'} onClick={() => setView('done')}>Done</button>
        </div>
        <div className="row">
          <label className="row">Type <select value={type} onChange={(e) => setType(e.target.value)}><option value="">All</option>{types.map((t) => <option key={t} value={t}>{TYPE_LABEL[t]} {s?.byType[t] ? `(${s.byType[t]})` : ''}</option>)}</select></label>
          <label className="row">Channel <select value={channel} onChange={(e) => setChannel(e.target.value)}><option value="">All</option>{['email', 'web', 'whatsapp', 'document'].map((c) => <option key={c}>{c}</option>)}</select></label>
          <label className="row">Assigned to <select value={assignee} onChange={(e) => setAssignee(e.target.value)}><option value="">Anyone</option>{members.map((m) => <option key={m}>{m}</option>)}</select></label>
        </div>
      </section>
      {msg && <p className={isErr ? 'err' : 'ok'} role={isErr ? 'alert' : 'status'}>{msg}</p>}
      {work && !work.tasks.length && <p className="muted">{view === 'open' ? 'Nothing needs you right now. New follow-ups appear here when a customer goes quiet.' : 'Nothing completed yet.'}</p>}
      {work?.tasks.map((t) => {
        const canSend = (t.type === 'follow_up' || t.type === 'invoice_reminder') && !!t.draft; const text = drafts[t.taskId] ?? t.draft;
        return (
          <article key={t.taskId} className="card stack">
            <div className="row" style={{ justifyContent: 'space-between' }}>
              <h3>{t.title}</h3>
              <div className="row"><span className={`tag ${tone(t.priority)}`}>{t.priority}</span><span className="tag">{TYPE_LABEL[t.type] ?? t.type}</span>{t.channel && <span className="tag">{t.channel}</span>}<span className={`tag ${t.status === 'done' ? 'ok' : t.status === 'failed' ? 'bad' : t.status === 'needs_approval' ? 'hold' : ''}`}>{t.status.replace('_', ' ')}</span></div>
            </div>
            <span className="muted">{t.detail} · {ago(t.createdAt)}{t.assignee ? ` · assigned to ${t.assignee}` : ''}</span>
            {t.error && <p className="err">Last attempt failed: {t.error}</p>}
            {canSend && (view === 'open') && <label>Message{t.to ? ` to ${t.to}` : ''}<textarea rows={6} value={text} onChange={(e) => setDrafts({ ...drafts, [t.taskId]: e.target.value })} /></label>}
            {t.status === 'done' && t.sentVia && <span className="muted">Handled via {t.sentVia}</span>}
            <details open={open === t.taskId} onToggle={(e) => setOpen((e.target as HTMLDetailsElement).open ? t.taskId : '')}><summary className="muted" style={{ cursor: 'pointer' }}>Why am I seeing this?</summary>
              <p>{WHY[t.type]}</p><p className="muted">Based on: {t.channel || 'your records'} activity{t.dealId ? ` (record ${t.dealId.slice(0, 12)})` : ''}. Timing and wording rules are in Automations.</p></details>
            {view === 'open' && <div className="row">
              {canSend && <button className="btn primary" disabled={!!busy || !t.to} title={t.to ? '' : 'No email address for this customer'} onClick={() => act(t, 'approve', { text }, 'Sent.')}>{t.status === 'failed' ? 'Retry send' : 'Approve and send'}</button>}
              {t.type === 'document_review' && <button className="btn primary" disabled={!!busy} onClick={() => act(t, 'approve', {}, 'Approved.')}>Approve details</button>}
              {t.type === 'connection_attention' && <button className="btn primary" onClick={() => go('Integrations')}>Open Integrations</button>}
              {t.type !== 'connection_attention' && <button className="btn" disabled={!!busy} onClick={() => act(t, 'done', {}, 'Marked done.')}>{canSend ? 'I did this myself' : 'Mark done'}</button>}
              <button className="btn" disabled={!!busy} onClick={() => act(t, 'snooze', { hours: 24 }, 'Hidden for 24 hours.')}>Snooze 1 day</button>
              <button className="btn danger" disabled={!!busy} onClick={() => act(t, 'reject', {}, 'Dismissed.')}>Dismiss</button>
              <label className="row">Assign <select value={t.assignee ?? ''} disabled={!!busy} onChange={(e) => act(t, 'assign', { assignee: e.target.value }, 'Assigned.')}><option value="">Nobody</option>{members.map((m) => <option key={m}>{m}</option>)}</select></label>
            </div>}
          </article>
        );
      })}
      {!isAdmin && <p className="muted">Anyone on your team can approve and send. Changing the rules needs an admin.</p>}
    </div>
  );
}
