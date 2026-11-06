'use client';
import { useEffect, useState } from 'react';
import { api, type Conv, type Docs, type Lead, type Message, type Plugin } from '@/lib/api';
import { CountUp, DayBars, Segments } from '@/components/charts';

type Go = (tab: 'Customers' | 'Emails' | 'Business info' | 'Features') => void;
type Gap = { id: string; question: string; at: number };
type Data = { leads: Lead[]; convs: Conv[]; msgs: Message[]; plugins: Plugin[]; docs: Docs; siteKey: string | null; origins: string[] };

const WEEK = 7 * 86400;
const MINUTES_SAVED_PER_CHAT = 3; // a rough, stated assumption: time to answer a routine enquiry by hand
const DAYS = 14;
const dayKey = (t: number) => new Date(t * 1000).toISOString().slice(0, 10);
const lastDays = () => Array.from({ length: DAYS }, (_, i) => dayKey(Date.now() / 1000 - (DAYS - 1 - i) * 86400));
const ago = (t: number) => { const m = Math.max(1, Math.round((Date.now() / 1000 - t) / 60)); return m < 60 ? `${m} min ago` : m < 1440 ? `${Math.round(m / 60)} h ago` : `${Math.round(m / 1440)} d ago`; };

export default function Home({ go }: { go: Go }) {
  const [d, setD] = useState<Data | null>(null);
  const [err, setErr] = useState(''); const [gaps, setGaps] = useState<Gap[]>([]); const [drafts, setDrafts] = useState<Record<string, { q: string; a: string }>>({}); const [note, setNote] = useState(''); const [busyGap, setBusyGap] = useState('');
  const loadGaps = () => api<Gap[]>('GET', '/knowledge/gaps').then(setGaps).catch(() => undefined);
  useEffect(() => { loadGaps(); }, []);
  async function resolve(id: string, how: 'answer' | 'dismiss') {
    const d = drafts[id]; setBusyGap(id); setNote('');
    try { await api('POST', `/knowledge/gaps/${id}/${how}`, how === 'answer' ? { question: d?.q ?? gaps.find((g) => g.id === id)?.question, answer: d?.a ?? '' } : {}); await loadGaps(); if (how === 'answer') setNote('Saved. The assistant will know this in about a minute.'); }
    catch (e) { setNote((e as Error).message); } finally { setBusyGap(''); }
  }
  useEffect(() => {
    Promise.all([
      api<Lead[]>('GET', '/leads'), api<Conv[]>('GET', '/conversations'), api<Message[]>('GET', '/messages'),
      api<Plugin[]>('GET', '/plugins'), api<Docs>('GET', '/documents'),
      api<{ key: string | null; allowedOrigins: string[] }>('GET', '/channels/web').catch(() => ({ key: null, allowedOrigins: [] as string[] })),
    ]).then(([leads, convs, msgs, plugins, docs, web]) => setD({ leads, convs, msgs, plugins, docs, siteKey: web.key, origins: web.allowedOrigins }))
      .catch((e: Error) => setErr(e.message));
  }, []);

  if (err) return <p className="err" role="alert">{err}</p>;
  if (!d) return <p className="muted">Loading…</p>;

  const since = Date.now() / 1000 - WEEK;
  const week = d.convs.filter((c) => c.lastAt >= since);
  const newLeads = d.leads.filter((l) => l.status === 'COMPLETE' && l.updatedAt >= since);
  const waitingPeople = d.leads.filter((l) => l.status === 'HANDOFF');
  const waitingDrafts = d.msgs.filter((m) => m.status === 'PENDING_APPROVAL');
  const installed = (id: string) => d.plugins.some((p) => p.pluginId === id && p.installed);
  const steps = [
    { done: d.docs.documents.length > 0, title: 'Tell the assistant about your business', text: 'Upload your prices, services, areas and opening hours. It only answers from these.', tab: 'Business info' as const },
    { done: installed('conversation-agent'), title: 'Turn on the customer assistant', text: 'Switch on the assistant that answers customers and captures their details.', tab: 'Features' as const },
    { done: !!d.siteKey, title: 'Put the chat on your website', text: 'Copy one line of code into your site. Customers can then chat with you any time.', tab: 'Customers' as const },
    { done: installed('email-automation'), title: 'Let it draft email replies (optional)', text: 'Replies it is unsure about wait for your approval. Nothing is sent without your say-so.', tab: 'Features' as const },
  ];
  const todo = steps.filter((s) => !s.done);
  const needs = waitingPeople.length + waitingDrafts.length;
  const days = lastDays();
  const recent = [...d.leads].sort((a, b) => b.updatedAt - a.updatedAt).slice(0, 6);

  return (
    <div className="stack">
      <section className="card stack">
        <h2>What Hivemate does for your business</h2>
        <p>It answers your customers&apos; questions at any hour using your own prices and hours, collects the details of anyone who wants a job done, and tells you about it. It never makes up a price, and anything sensitive goes to you.</p>
      </section>

      {needs > 0 && (
        <section className="card stack" aria-label="Needs you">
          <h3>Needs you ({needs})</h3>
          {waitingPeople.map((l) => (
            <div key={l.SK} className="row" style={{ justifyContent: 'space-between' }}>
              <span><strong>{l.collected.name || 'A customer'}</strong> needs a person: {l.handoffReason || 'asked for a human'} <span className="muted">· {ago(l.updatedAt)}</span></span>
              <button className="btn primary" onClick={() => go('Customers')}>Open</button>
            </div>
          ))}
          {waitingDrafts.map((m) => (
            <div key={m.SK} className="row" style={{ justifyContent: 'space-between' }}>
              <span>Email from <strong>{m.from}</strong> is waiting for your approval: {m.subject || '(no subject)'}</span>
              <button className="btn primary" onClick={() => go('Emails')}>Review</button>
            </div>
          ))}
        </section>
      )}

      {(gaps.length > 0 || note) && (
        <section className="card stack" aria-label="Questions to answer">
          <h3>Questions customers asked that the assistant could not answer ({gaps.length})</h3>
          <p className="muted" style={{ margin: 0 }}>Write the answer once and the assistant will use it from now on. It is added to your public knowledge, so only write what customers may be told.</p>
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

      <section aria-label="This week" className="grid" style={{ gridTemplateColumns: 'repeat(auto-fit,minmax(190px,1fr))' }}>
        <Stat n={week.length} label="Customer chats this week" />
        <Stat n={newLeads.length} label="New leads this week" hint="Name and phone captured" />
        <Stat n={waitingPeople.length} label="Waiting for a person" />
        <Stat n={Math.round((week.length * MINUTES_SAVED_PER_CHAT) / 60 * 10) / 10} label="Hours of replies handled" hint={`Estimate: ${MINUTES_SAVED_PER_CHAT} min per chat`} />
      </section>

      <section className="grid" aria-label="Activity" style={{ gridTemplateColumns: 'repeat(auto-fit,minmax(340px,1fr))' }}>
        <DayBars title="Customer chats per day" unit="chats" data={days.map((k) => ({ day: k, v: d.convs.filter((c) => dayKey(c.createdAt ?? c.lastAt) === k).length }))} />
        <DayBars title="Leads captured per day" unit="leads" color="var(--s3)" data={days.map((k) => ({ day: k, v: d.leads.filter((l) => l.status === 'COMPLETE' && dayKey(l.updatedAt) === k).length }))} />
      </section>
      <Segments title="What happened to your enquiries" empty="No enquiries yet. Once customers chat, you will see how they ended up."
        parts={[
          { label: 'Lead captured', value: d.leads.filter((l) => l.status === 'COMPLETE').length, color: 'var(--s3)' },
          { label: 'Answered, still gathering details', value: d.leads.filter((l) => l.status === 'COLLECTING').length, color: 'var(--s1)' },
          { label: 'Needs a person', value: waitingPeople.length, color: 'var(--s2)' },
        ]} />

      <section className="grid" aria-label="Your business">
        <div className="card stack">
          <h3>Your website</h3>
          {d.siteKey ? <>
            <p className="muted" style={{ margin: 0 }}>The chat is live for:</p>
            {d.origins.length ? d.origins.map((o) => <div key={o} className="mono">{o}</div>) : <div className="muted">Any website (not restricted yet)</div>}
          </> : <p className="muted" style={{ margin: 0 }}>The chat is not on a website yet.</p>}
          <button className="btn" onClick={() => go('Customers')}>{d.siteKey ? 'Manage website chat' : 'Add chat to your website'}</button>
        </div>
        <div className="card stack">
          <h3>What the assistant knows</h3>
          {d.docs.documents.length ? <>
            {d.docs.documents.slice(0, 5).map((f) => <div key={f.name} className="row" style={{ justifyContent: 'space-between' }}><span className="mono">{f.name}</span><span className="muted">{Math.max(1, Math.round(f.size / 1024))} KB</span></div>)}
            {d.docs.documents.length > 5 && <span className="muted">+ {d.docs.documents.length - 5} more</span>}
            <span className="muted">{d.docs.lastSync ? `Last learned: ${d.docs.lastSync.status.toLowerCase()}` : 'Not learned yet: press Sync in Business info'}</span>
          </> : <p className="muted" style={{ margin: 0 }}>No documents yet. Upload your prices, services and hours.</p>}
          <button className="btn" onClick={() => go('Business info')}>Manage</button>
        </div>
        <div className="card stack">
          <h3>Switched on</h3>
          {d.plugins.filter((p) => p.installed).map((p) => <div key={p.pluginId}>✓ {p.name}</div>)}
          {!d.plugins.some((p) => p.installed) && <p className="muted" style={{ margin: 0 }}>Nothing yet.</p>}
          <button className="btn" onClick={() => go('Features')}>Manage</button>
        </div>
      </section>

      <section className="card stack" aria-label="Recent enquiries">
        <div className="row" style={{ justifyContent: 'space-between' }}><h3>Recent enquiries</h3><button className="btn" onClick={() => go('Customers')}>See all and read the chats</button></div>
        {!recent.length && <p className="muted">No enquiries yet.</p>}
        {recent.map((l) => (
          <div key={l.SK} className="row" style={{ justifyContent: 'space-between', borderTop: '1px solid var(--line)', paddingTop: 8 }}>
            <span><strong>{l.collected.name || 'Unknown customer'}</strong>{l.collected.need ? ` · ${l.collected.need}` : ''}
              <br /><span className="muted">{[l.collected.location, l.collected.timing, l.collected.phone].filter(Boolean).join(' · ') || 'No details yet'}</span></span>
            <span className="row"><span className="tag">{l.channel}</span><span className={`tag ${l.status === 'COMPLETE' ? 'ok' : l.status === 'HANDOFF' ? 'hold' : ''}`}>{l.status === 'HANDOFF' && <i className="pulse" />}{l.status === 'COMPLETE' ? 'lead' : l.status === 'HANDOFF' ? 'needs you' : 'chatting'}</span><span className="muted">{ago(l.updatedAt)}</span></span>
          </div>
        ))}
      </section>

      {todo.length > 0 && (
        <section className="card stack" aria-label="Get set up">
          <h3>Get set up ({steps.length - todo.length} of {steps.length} done)</h3>
          {steps.map((s) => (
            <div key={s.title} className="row" style={{ justifyContent: 'space-between', opacity: s.done ? 0.55 : 1 }}>
              <span><strong>{s.done ? '✓ ' : ''}{s.title}</strong><br /><span className="muted">{s.text}</span></span>
              {!s.done && <button className="btn" onClick={() => go(s.tab)}>Do this</button>}
            </div>
          ))}
        </section>
      )}

      {!needs && !todo.length && <p className="muted">Nothing needs you right now.</p>}
    </div>
  );
}

function Stat({ n, label, hint }: { n: number; label: string; hint?: string }) {
  return <div className="card"><div className="hero-num"><CountUp value={n} decimals={n % 1 ? 1 : 0} /></div><div>{label}</div>{hint && <div className="muted" style={{ fontSize: 13 }}>{hint}</div>}</div>;
}
