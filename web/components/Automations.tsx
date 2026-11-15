'use client';
import { useCallback, useEffect, useState } from 'react';
import { api, type Pack, type Policy } from '@/lib/api';

const ACTIONS: { id: string; label: string; help: string; locked?: boolean }[] = [
  { id: 'follow_up', label: 'Follow up quiet enquiries', help: 'A short check-in when a customer has not replied.' },
  { id: 'quote_follow_up', label: 'Follow up a quote', help: 'A check-in after a quote was sent.' },
  { id: 'invoice_reminder', label: 'Invoice reminders', help: 'Polite payment reminders for overdue Xero invoices. The final, firmest step always needs you.' },
  { id: 'quote', label: 'Sending quotes', help: 'Quotes always need your approval.', locked: true },
  { id: 'refund', label: 'Refunds', help: 'Refunds always need your approval.', locked: true },
];
const MODES = [['assist', 'Assist: it tells me, I do it'], ['approve', 'Approve: it drafts, I approve'], ['automate', 'Automate: it sends within limits']] as const;
const CAD: [string, string][] = [['noReplyHours', 'Flag an unanswered enquiry after (hours)'], ['followUpAfterHours', 'Follow up after we replied (hours)'], ['quoteFollowUpDays', 'Follow up a quote after (days)'], ['maxFollowUps', 'Follow-ups before a lead goes cold']];
const MIN: [string, string][] = [['follow_up', 'Writing a follow-up'], ['quote_follow_up', 'Following up a quote'], ['invoice_reminder', 'An invoice reminder'], ['email_drafted', 'Drafting an email reply'], ['document_extracted', 'Entering an invoice or receipt']];

export default function Automations({ isAdmin }: { isAdmin: boolean }) {
  const [p, setP] = useState<Policy | null>(null); const [packs, setPacks] = useState<Pack[]>([]); const [msg, setMsg] = useState(''); const [isErr, setIsErr] = useState(false); const [busy, setBusy] = useState(false);
  const load = useCallback(() => Promise.all([api<Policy>('GET', '/policy'), api<Pack[]>('GET', '/packs')]).then(([a, b]) => { setP(a); setPacks(b); }).catch((e: Error) => { setIsErr(true); setMsg(e.message); }), []);
  useEffect(() => { load(); }, [load]);
  async function save(next: Policy, ok = 'Saved.') {
    setBusy(true); setMsg(''); setIsErr(false);
    try { setP(await api<Policy>('PUT', '/policy', next)); setMsg(ok); setPacks(await api<Pack[]>('GET', '/packs')); } catch (e) { setIsErr(true); setMsg((e as Error).message); } finally { setBusy(false); }
  }
  async function enable(id: string) { setBusy(true); setMsg(''); try { await api('POST', `/packs/${id}/enable`); await load(); setMsg('Pack turned on.'); } catch (e) { setIsErr(true); setMsg((e as Error).message); } finally { setBusy(false); } }
  if (!p) return <p className="muted">{msg || 'Loading…'}</p>;
  const num = (v: string) => (v === '' ? 0 : Number(v));
  return (
    <div className="stack">
      {msg && <p className={isErr ? 'err' : 'ok'} role={isErr ? 'alert' : 'status'}>{msg}</p>}
      {!isAdmin && <p className="muted">Only an admin can change these settings.</p>}
      <section className="card stack"><h2>Ready-made packs</h2>
        <div className="grid">{packs.map((k) => (
          <div key={k.id} className="card stack"><div className="row" style={{ justifyContent: 'space-between' }}><h3>{k.name}</h3><span className={`tag ${k.enabled ? 'ok' : ''}`}>{k.planned ? 'planned' : k.enabled ? 'on' : 'off'}</span></div>
            <span className="muted">{k.blurb}</span>
            {k.missing.map((m) => <span key={m} className="err">Needs: {m}</span>)}
            {!k.planned && !k.enabled && <button className="btn primary" disabled={!isAdmin || busy || k.missing.length > 0} onClick={() => enable(k.id)}>Turn on</button>}
          </div>))}</div></section>

      <section className="card stack"><h2>How much can Hivemate do by itself?</h2>
        <p className="muted">Start on Approve. Move an action to Automate only when you trust the wording. Automatic sends only happen {p.sendWindow.start} to {p.sendWindow.end}, Monday to Friday, and only to customers with an email address.</p>
        {ACTIONS.map((a) => (
          <div key={a.id} className="lockrow"><div><strong>{a.label}</strong><br /><span className="muted">{a.help}</span></div>
            <select aria-label={a.label} disabled={!isAdmin || busy || a.locked} value={p.modes[a.id]} onChange={(e) => save({ ...p, modes: { ...p.modes, [a.id]: e.target.value as 'assist' | 'approve' | 'automate' } })}>
              {MODES.filter(([m]) => !(a.locked && m === 'automate')).map(([m, l]) => <option key={m} value={m}>{l}</option>)}</select></div>))}
      </section>

      <section className="card stack"><h2>Switch automations on or off</h2>
        {[['follow_up', 'Follow-ups and unanswered-enquiry alerts'], ['invoice_reminder', 'Invoice reminders'], ['connector_sync', 'Syncing connected systems']].map(([k, l]) => (
          <div key={k} className="row" style={{ justifyContent: 'space-between' }}><span>{l} <span className={`tag ${p.paused[k] ? 'hold' : 'ok'}`}>{p.paused[k] ? 'paused' : 'running'}</span></span>
            <button className="btn" disabled={!isAdmin || busy} onClick={() => save({ ...p, paused: { ...p.paused, [k]: !p.paused[k] } }, p.paused[k] ? 'Resumed.' : 'Paused.')}>{p.paused[k] ? 'Resume' : 'Pause'}</button></div>))}
      </section>

      <section className="card stack"><h2>Timing</h2>
        <div className="grid">{CAD.map(([k, l]) => <label key={k}>{l}<input type="number" min={0} disabled={!isAdmin} value={p.cadence[k]} onChange={(e) => setP({ ...p, cadence: { ...p.cadence, [k]: num(e.target.value) } })} /></label>)}</div>
        <h3>Minutes a person would spend (used for the time-saved estimate)</h3>
        <div className="grid">{MIN.map(([k, l]) => <label key={k}>{l}<input type="number" min={0} max={240} disabled={!isAdmin} value={p.minutes[k]} onChange={(e) => setP({ ...p, minutes: { ...p.minutes, [k]: num(e.target.value) } })} /></label>)}</div>
        <div><button className="btn primary" disabled={!isAdmin || busy} onClick={() => save(p)}>Save timing and estimates</button></div>
      </section>
    </div>
  );
}
