'use client';
import { useEffect, useState } from 'react';
import { api, type Connection, type Conv, type Docs, type Impact, type Lead, type Message, type Plugin, type Task, type Work } from '@/lib/api';
import { CountUp, DayBars, Funnel, Ring, Spark } from '@/components/charts';
import { Icon, IconTile } from '@/components/icons';

type Go = (tab: 'Work Queue' | 'Conversations' | 'Knowledge' | 'Settings' | 'Impact' | 'Integrations' | 'Customers' | 'Automations', filter?: string) => void;
type Gap = { id: string; question: string; at: number };
type Data = { leads: Lead[]; convs: Conv[]; msgs: Message[]; plugins: Plugin[]; docs: Docs; siteKey: string | null; work: Work; impact: Impact; conns: Connection[] };

const DAYS = 14;
const dayKey = (t: number) => new Date(t * 1000).toISOString().slice(0, 10);
const lastDays = () => Array.from({ length: DAYS }, (_, i) => dayKey(Date.now() / 1000 - (DAYS - 1 - i) * 86400));
const ago = (t: number) => { const m = Math.max(1, Math.round((Date.now() / 1000 - t) / 60)); return m < 60 ? `${m} min ago` : m < 1440 ? `${Math.round(m / 60)} h ago` : `${Math.round(m / 1440)} d ago`; };
const TASK_ICON: Record<string, string> = { follow_up: 'clock', reply_overdue: 'reply', cold_lead: 'snow', invoice_reminder: 'invoice', document_review: 'doc', connection_attention: 'plug' };
const TONE: Record<string, string> = { urgent: 'var(--bad)', high: 'var(--amber)', normal: 'var(--s1)' };

export default function Home({ go }: { go: Go }) {
  const [d, setD] = useState<Data | null>(null);
  const [err, setErr] = useState(''); const [gaps, setGaps] = useState<Gap[]>([]); const [drafts, setDrafts] = useState<Record<string, { q: string; a: string }>>({}); const [note, setNote] = useState(''); const [busyGap, setBusyGap] = useState('');
  const loadGaps = () => api<Gap[]>('GET', '/knowledge/gaps').then(setGaps).catch(() => undefined);
  useEffect(() => { loadGaps(); }, []);
  async function resolve(id: string, how: 'answer' | 'dismiss') {
    const x = drafts[id]; setBusyGap(id); setNote('');
    try { await api('POST', `/knowledge/gaps/${id}/${how}`, how === 'answer' ? { question: x?.q ?? gaps.find((g) => g.id === id)?.question, answer: x?.a ?? '' } : {}); await loadGaps(); if (how === 'answer') setNote('Saved. The assistant will know this in about a minute.'); }
    catch (e) { setNote((e as Error).message); } finally { setBusyGap(''); }
  }
  useEffect(() => {
    Promise.all([
      api<Lead[]>('GET', '/leads'), api<Conv[]>('GET', '/conversations'), api<Message[]>('GET', '/messages'),
      api<Plugin[]>('GET', '/plugins'), api<Docs>('GET', '/documents'),
      api<{ key: string | null }>('GET', '/channels/web').catch(() => ({ key: null })),
      api<Work>('GET', '/work'), api<Impact>('GET', `/impact?days=${DAYS}`), api<Connection[]>('GET', '/connections').catch(() => [] as Connection[]),
    ]).then(([leads, convs, msgs, plugins, docs, web, work, impact, conns]) => setD({ leads, convs, msgs, plugins, docs, siteKey: web.key, work, impact, conns }))
      .catch((e: Error) => setErr(e.message));
  }, []);

  if (err) return <p className="err" role="alert">{err}</p>;
  if (!d) return <p className="muted">Loading…</p>;

  const s = d.work.summary, m = d.impact.measured;
  const waitingPeople = d.leads.filter((l) => l.status === 'HANDOFF');
  const waitingDrafts = d.msgs.filter((x) => x.status === 'PENDING_APPROVAL');
  const installed = (id: string) => d.plugins.some((p) => p.pluginId === id && p.installed);
  const steps = [
    { done: d.docs.documents.length > 0, title: 'Tell the assistant about your business', tab: 'Knowledge' as const },
    { done: installed('conversation-agent'), title: 'Turn on the customer assistant', tab: 'Automations' as const },
    { done: !!d.siteKey, title: 'Put the chat on your website', tab: 'Conversations' as const },
    { done: installed('email-automation'), title: 'Let it draft email replies', tab: 'Automations' as const },
    { done: d.conns.some((c) => c.connected), title: 'Connect Outlook or Xero', tab: 'Integrations' as const },
  ];
  const doneSteps = steps.filter((x) => x.done).length;
  const days = lastDays();
  const trend = d.impact.daily.slice(-DAYS).map((x) => x.tasks);
  const chatsTrend = days.map((k) => d.convs.filter((c) => dayKey(c.createdAt ?? c.lastAt) === k).length);
  const topTasks: Task[] = d.work.tasks.slice(0, 5);
  const p = d.impact.pipeline;
  const systems = [
    ...d.conns.map((c) => ({ name: c.label, state: c.status === 'connected' ? 'ok' : c.connected ? 'bad' : 'off', text: c.status === 'connected' ? `Connected · ${c.account}` : c.connected ? 'Needs reconnecting' : 'Not connected' })),
    { name: 'Website chat', state: d.siteKey ? 'ok' : 'off', text: d.siteKey ? 'Live on your site' : 'Not added yet' },
    { name: 'Email drafting', state: installed('email-automation') ? 'ok' : 'off', text: installed('email-automation') ? 'On' : 'Off' },
  ];
  const stateColor = (x: string) => (x === 'ok' ? 'var(--fern)' : x === 'bad' ? 'var(--bad)' : 'var(--line)');

  return (
    <div className="stack" style={{ gap: 18 }}>
      <section className="kpis" aria-label="Today">
        <button className="card kpi2" onClick={() => go('Work Queue')}>
          <div className="top"><IconTile name="queue" tone="fern" /><div style={{ width: 110 }}><Spark data={trend} /></div></div>
          <div className="num"><CountUp value={s.open} /></div><div className="lbl">Things to do</div>
          <div className="hint">{s.urgent} urgent <Icon name="arrow" size={13} /></div>
        </button>
        <button className="card kpi2" onClick={() => go('Work Queue', 'reply_overdue')}>
          <div className="top"><IconTile name="reply" tone={s.byType.reply_overdue ? 'bad' : 'muted'} /></div>
          <div className="num"><CountUp value={s.byType.reply_overdue ?? 0} /></div><div className="lbl">Customers waiting for a reply</div>
          <div className="hint">Nobody has answered yet <Icon name="arrow" size={13} /></div>
        </button>
        <button className="card kpi2" onClick={() => go('Work Queue', 'follow_up')}>
          <div className="top"><IconTile name="clock" tone="amber" /></div>
          <div className="num"><CountUp value={s.byType.follow_up ?? 0} /></div><div className="lbl">Follow-ups ready to send</div>
          <div className="hint">{s.needsApproval} waiting for approval <Icon name="arrow" size={13} /></div>
        </button>
        <button className="card kpi2" onClick={() => go('Impact')}>
          <div className="top"><IconTile name="spark" tone="s1" /><div style={{ width: 110 }}><Spark data={chatsTrend} color="var(--s1)" /></div></div>
          <div className="num"><CountUp value={d.impact.estimated.hoursSaved} decimals={1} /><span style={{ fontSize: 16, fontWeight: 500 }}> h</span></div><div className="lbl">Time saved, last {DAYS} days</div>
          <div className="hint">Estimate · see how <Icon name="arrow" size={13} /></div>
        </button>
      </section>

      <section className="two">
        <div className="card stack" aria-label="Needs your attention">
          <div className="row" style={{ justifyContent: 'space-between' }}><h2>Needs your attention</h2><button className="btn" onClick={() => go('Work Queue')}>Open Work Queue</button></div>
          <div className="attn">
            {waitingPeople.map((l) => (
              <div key={l.SK} className="attn-row" style={{ ['--c' as string]: 'var(--bad)' }}><IconTile name="users" tone="bad" size={34} />
                <div className="txt"><strong>{l.collected.name || 'A customer'} asked for a person</strong><span>{l.handoffReason || 'Requested a human'} · {ago(l.updatedAt)}</span></div>
                <button className="btn primary" onClick={() => go('Conversations')}>Open</button></div>
            ))}
            {topTasks.map((t) => (
              <div key={t.taskId} className="attn-row" style={{ ['--c' as string]: TONE[t.priority] }}><IconTile name={TASK_ICON[t.type] ?? 'queue'} tone={t.priority === 'urgent' ? 'bad' : t.priority === 'high' ? 'amber' : 's1'} size={34} />
                <div className="txt"><strong>{t.title}</strong><span>{t.detail}</span></div>
                <button className="btn" onClick={() => go('Work Queue', t.type)}>Review</button></div>
            ))}
            {waitingDrafts.slice(0, 3).map((x) => (
              <div key={x.SK} className="attn-row" style={{ ['--c' as string]: 'var(--amber)' }}><IconTile name="mail" tone="amber" size={34} />
                <div className="txt"><strong>Reply drafted for {x.from}</strong><span>{x.subject || '(no subject)'} · waiting for your approval</span></div>
                <button className="btn" onClick={() => go('Conversations', 'Email drafts')}>Review</button></div>
            ))}
            {!waitingPeople.length && !topTasks.length && !waitingDrafts.length && <div className="row" style={{ padding: '18px 4px' }}><IconTile name="check" tone="fern" /><span><strong>All clear.</strong><br /><span className="muted">New follow-ups appear here when a customer goes quiet.</span></span></div>}
          </div>
        </div>
        <div className="card stack" aria-label="How you are doing">
          <h2>How you are doing</h2>
          <div className="rings three">
            <Ring value={m.respondedWithinHourPct} label="Answered within an hour" color="var(--fern)" size={92} />
            <Ring value={m.followUpRatePct} label="Quiet enquiries followed up" sub={`${m.followUpsActioned ?? 0} of ${m.followUpsDue ?? 0}`} color="var(--s1)" size={92} />
            <Ring value={m.executionSuccessPct} label="Sends that succeeded" color="var(--s3)" size={92} />
          </div>
          <button className="btn" onClick={() => go('Impact')}>See business impact</button>
        </div>
      </section>

      <section className="two">
        <div className="card stack" aria-label="Enquiry pipeline">
          <div className="row" style={{ justifyContent: 'space-between' }}><h2>Where your enquiries are</h2><button className="btn" onClick={() => go('Customers')}>Open the board</button></div>
          <Funnel onPick={() => go('Customers')} stages={[
            { id: 'new', label: 'New', value: p.new ?? 0, color: 'var(--s1)' }, { id: 'responded', label: 'Replied', value: p.responded ?? 0, color: 'var(--s3)' },
            { id: 'followed_up', label: 'Followed up', value: p.followed_up ?? 0, color: 'var(--s4)' }, { id: 'quote_sent', label: 'Quote sent', value: p.quote_sent ?? 0, color: 'var(--amber)' },
            { id: 'won', label: 'Won', value: p.won ?? 0, color: 'var(--fern)' }, { id: 'cold', label: 'Cold or lost', value: (p.cold ?? 0) + (p.lost ?? 0), color: 'var(--muted)' }]} />
          <span className="muted">{m.leadsRecovered ?? 0} recovered after a follow-up · {m.enquiries ?? 0} new in the last {DAYS} days</span>
        </div>
        <div className="card stack" aria-label="Connected systems">
          <div className="row" style={{ justifyContent: 'space-between' }}><h2>Connected systems</h2><button className="btn" onClick={() => go('Integrations')}>Manage</button></div>
          <div>{systems.map((x) => (
            <div key={x.name} className="sys"><i className="dot" style={{ ['--c' as string]: stateColor(x.state) }} /><span style={{ flex: 1 }}><strong>{x.name}</strong><br /><span className="muted" style={{ fontSize: 13 }}>{x.text}</span></span></div>
          ))}</div>
        </div>
      </section>

      <section className="grid" aria-label="Activity" style={{ gridTemplateColumns: 'repeat(auto-fit,minmax(340px,1fr))' }}>
        <DayBars title="Customer chats per day" unit="chats" data={days.map((k, i) => ({ day: k, v: chatsTrend[i] }))} />
        <DayBars title="Leads captured per day" unit="leads" color="var(--s3)" data={days.map((k) => ({ day: k, v: d.leads.filter((l) => l.status === 'COMPLETE' && dayKey(l.updatedAt) === k).length }))} />
      </section>

      {(gaps.length > 0 || note) && (
        <section className="card stack" aria-label="Questions to answer">
          <div className="row"><IconTile name="book" tone="s4" /><div><h2>Questions the assistant could not answer ({gaps.length})</h2><span className="muted">Write the answer once and it is used from then on. It joins your public knowledge, so only write what customers may be told.</span></div></div>
          {note && <p className="ok" role="status">{note}</p>}
          {gaps.slice(0, 5).map((g) => (
            <div key={g.id} className="stack" style={{ borderTop: '1px solid var(--line)', paddingTop: 10 }}>
              <label>Customer asked<input value={drafts[g.id]?.q ?? g.question} onChange={(e) => setDrafts({ ...drafts, [g.id]: { q: e.target.value, a: drafts[g.id]?.a ?? '' } })} /></label>
              <label>Your answer<textarea rows={2} value={drafts[g.id]?.a ?? ''} onChange={(e) => setDrafts({ ...drafts, [g.id]: { q: drafts[g.id]?.q ?? g.question, a: e.target.value } })} placeholder="e.g. Yes, we clean ovens for $40 extra." /></label>
              <div className="row"><button className="btn primary" disabled={busyGap === g.id || !(drafts[g.id]?.a ?? '').trim()} onClick={() => resolve(g.id, 'answer')}>Add to knowledge</button>
                <button className="btn" disabled={busyGap === g.id} onClick={() => resolve(g.id, 'dismiss')}>Not relevant</button><span className="muted">{ago(g.at / 1000)}</span></div>
            </div>
          ))}
        </section>
      )}

      {doneSteps < steps.length && (
        <section className="card stack" aria-label="Get set up">
          <div className="row" style={{ justifyContent: 'space-between' }}><h2>Get set up</h2><span className="muted">{doneSteps} of {steps.length} done</span></div>
          <div className="progress"><i style={{ width: `${(doneSteps / steps.length) * 100}%` }} /></div>
          <div className="steps">{steps.map((x, i) => (
            <div key={x.title} className={`step ${x.done ? 'done' : ''}`}><span className="n">{x.done ? <Icon name="check" size={14} /> : i + 1}</span><span style={{ flex: 1 }}>{x.title}</span>
              {!x.done && <button className="btn" onClick={() => go(x.tab)}>Do this</button>}</div>
          ))}</div>
        </section>
      )}
    </div>
  );
}
