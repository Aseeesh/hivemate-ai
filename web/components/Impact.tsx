'use client';
import { useEffect, useState } from 'react';
import { api, type Impact as ImpactT } from '@/lib/api';
import { CountUp, DayBars, Segments } from '@/components/charts';

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
      <h2>Measured results</h2>
      <section className="grid" style={{ gridTemplateColumns: 'repeat(auto-fit,minmax(200px,1fr))' }}>
        <div className="card"><div className="hero-num"><CountUp value={n('enquiries')} /></div><div>Enquiries received</div></div>
        <div className="card"><div className="hero-num">{dur(m.medianResponseSeconds)}</div><div>Typical time to first reply</div><div className="muted">{pct(m.respondedWithinHourPct)} answered within an hour</div></div>
        <div className="card"><div className="hero-num">{pct(m.followUpRatePct)}</div><div>Quiet enquiries followed up</div><div className="muted">{n('followUpsActioned')} of {n('followUpsDue')} due</div></div>
        <div className="card"><div className="hero-num"><CountUp value={n('leadsRecovered')} /></div><div>Leads recovered</div><div className="muted">{n('leadsWentCold')} went cold · recovery {pct(m.recoveryRatePct)}</div></div>
        <div className="card"><div className="hero-num">{pct(m.executionSuccessPct)}</div><div>Sends that succeeded</div><div className="muted">{n('executionsFailed')} failed</div></div>
        <div className="card"><div className="hero-num"><CountUp value={n('manualInterventions')} /></div><div>Times a person stepped in</div><div className="muted">{n('approvalsCompleted')} approvals</div></div>
        <div className="card"><div className="hero-num"><CountUp value={n('invoiceRemindersSent')} /></div><div>Invoice reminders sent</div><div className="muted">{n('invoicesPaidAfterReminder')} paid afterwards</div></div>
        <button className="card kpi" onClick={() => go('Work Queue')}><div className="hero-num"><CountUp value={n('repliesOverdue')} /></div><div>Replies that were overdue</div><div className="muted">Open the Work Queue</div></button>
      </section>
      <section className="card stack">
        <h2>Estimated time saved</h2>
        <div className="hero-num"><CountUp value={d.estimated.hoursSaved} decimals={1} /> hours</div>
        <p className="muted" style={{ margin: 0 }}>{d.estimated.note} <button className="btn" onClick={() => go('Automations')}>Change the minutes</button></p>
        {d.estimated.basis.length ? <table><thead><tr><th>Task</th><th>Prepared</th><th>Minutes each</th><th>Minutes</th></tr></thead><tbody>{d.estimated.basis.map((b) => <tr key={b.type}><td>{b.type.replace(/_/g, ' ')}</td><td>{b.count}</td><td>{b.minutesEach}</td><td>{b.minutes}</td></tr>)}</tbody></table> : <p className="muted">No automated tasks yet.</p>}
      </section>
      <DayBars title="Tasks prepared or sent per day" unit="tasks" data={d.daily.map((x) => ({ day: x.day, v: x.tasks }))} />
      <Segments title="Where your enquiries are now" empty="No enquiries tracked yet." parts={[
        { label: 'New', value: d.pipeline.new ?? 0, color: 'var(--s1)' }, { label: 'Replied', value: (d.pipeline.responded ?? 0) + (d.pipeline.followed_up ?? 0), color: 'var(--s3)' },
        { label: 'Quote sent', value: d.pipeline.quote_sent ?? 0, color: 'var(--s4)' }, { label: 'Won', value: d.pipeline.won ?? 0, color: 'var(--fern)' }, { label: 'Went cold or lost', value: (d.pipeline.cold ?? 0) + (d.pipeline.lost ?? 0), color: 'var(--s2)' }]} />
      <p className="muted">Not measured: cost per task. Per-task cloud and third-party cost is not metered yet, so Hivemate does not show a made-up figure. These are workload and speed numbers, not a financial result.</p>
    </div>
  );
}
