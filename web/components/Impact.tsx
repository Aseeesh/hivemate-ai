'use client';
import { useEffect, useState } from 'react';
import { api, type Impact as ImpactT } from '@/lib/api';
import { CountUp, DayBars, Funnel, Ring } from '@/components/charts';
import { IconTile } from '@/components/icons';

const dur = (s: number | null) => (s == null ? 'no data yet' : s < 3600 ? `${Math.max(1, Math.round(s / 60))} min` : `${(s / 3600).toFixed(1)} h`);
const pct = (v: number | null) => (v == null ? 'no data yet' : `${v}%`);

export default function Impact({ go }: { go: (t: 'Automations' | 'Work Queue') => void }) {
  const [days, setDays] = useState(30); const [d, setD] = useState<ImpactT | null>(null); const [err, setErr] = useState('');
  useEffect(() => { api<ImpactT>('GET', `/impact?days=${days}`).then(setD).catch((e: Error) => setErr(e.message)); }, [days]);
  if (err) return <p className="err" role="alert">{err}</p>;
  if (!d) return <p className="muted">Loading…</p>;
  const m = d.measured as Record<string, number | null>; const n = (k: string) => (m[k] ?? 0) as number;
  return (
    <div className="stack">
      <div className="row" style={{ justifyContent: 'space-between' }}>
        <p className="muted" style={{ margin: 0 }}>Every figure below is counted from what actually happened in your account.</p>
        <label className="row">Period <select value={days} onChange={(e) => setDays(Number(e.target.value))}>{[7, 30, 90].map((x) => <option key={x} value={x}>Last {x} days</option>)}</select></label>
      </div>
      <section className="card stack"><h2>Measured results</h2>
        <div className="rings">
          <Ring value={m.respondedWithinHourPct} label="Answered within an hour" sub={`typical first reply ${dur(m.medianResponseSeconds)}`} size={132} />
          <Ring value={m.followUpRatePct} label="Quiet enquiries followed up" sub={`${n('followUpsActioned')} of ${n('followUpsDue')} due`} color="var(--s1)" size={132} />
          <Ring value={m.recoveryRatePct} label="Quiet leads recovered" sub={`${n('leadsRecovered')} back, ${n('leadsWentCold')} went cold`} color="var(--s4)" size={132} />
          <Ring value={m.executionSuccessPct} label="Sends that succeeded" sub={`${n('executionsFailed')} failed`} color="var(--s3)" size={132} />
        </div></section>
      <section className="kpis">
        {([['mail', 's1', n('enquiries'), 'Enquiries received', ''], ['trophy', 'fern', n('leadsRecovered'), 'Leads recovered', 'replied after a follow-up'], ['users', 'amber', n('manualInterventions'), 'Times a person stepped in', `${n('approvalsCompleted')} approvals`], ['invoice', 's4', n('invoiceRemindersSent'), 'Invoice reminders sent', `${n('invoicesPaidAfterReminder')} paid afterwards`]] as const).map(([i, t, v, l, h]) => (
          <div key={l} className="card kpi2" style={{ cursor: 'default' }}><div className="top"><IconTile name={i} tone={t} /></div><div className="num"><CountUp value={v} /></div><div className="lbl">{l}</div><div className="hint">{h}</div></div>
        ))}
        <button className="card kpi2" onClick={() => go('Work Queue')}><div className="top"><IconTile name="reply" tone="bad" /></div><div className="num"><CountUp value={n('repliesOverdue')} /></div><div className="lbl">Replies that were overdue</div><div className="hint">Open the Work Queue</div></button>
      </section>
      <section className="card stack">
        <h2>Estimated time saved</h2>
        <div className="hero-num"><CountUp value={d.estimated.hoursSaved} decimals={1} /> hours</div>
        <p className="muted" style={{ margin: 0 }}>{d.estimated.note} <button className="btn" onClick={() => go('Automations')}>Change the minutes</button></p>
        {d.estimated.basis.length ? <table><thead><tr><th>Task</th><th>Prepared</th><th>Minutes each</th><th>Minutes</th></tr></thead><tbody>{d.estimated.basis.map((b) => <tr key={b.type}><td>{b.type.replace(/_/g, ' ')}</td><td>{b.count}</td><td>{b.minutesEach}</td><td>{b.minutes}</td></tr>)}</tbody></table> : <p className="muted">No automated tasks yet.</p>}
      </section>
      <DayBars title="Tasks prepared or sent per day" unit="tasks" data={d.daily.map((x) => ({ day: x.day, v: x.tasks }))} />
      <section className="card stack"><h2>Where your enquiries are now</h2>
        <Funnel stages={[{ id: 'new', label: 'New', value: d.pipeline.new ?? 0, color: 'var(--s1)' }, { id: 'r', label: 'Replied', value: (d.pipeline.responded ?? 0) + (d.pipeline.followed_up ?? 0), color: 'var(--s3)' },
          { id: 'q', label: 'Quote sent', value: d.pipeline.quote_sent ?? 0, color: 'var(--amber)' }, { id: 'w', label: 'Won', value: d.pipeline.won ?? 0, color: 'var(--fern)' }, { id: 'c', label: 'Cold or lost', value: (d.pipeline.cold ?? 0) + (d.pipeline.lost ?? 0), color: 'var(--muted)' }]} /></section>
      <p className="muted">Not measured: cost per task. Per-task cloud and third-party cost is not metered yet, so Hivemate does not show a made-up figure. These are workload and speed numbers, not a financial result.</p>
    </div>
  );
}
