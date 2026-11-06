'use client';
import { useEffect, useState } from 'react';
import { api, type Conv, type Docs, type Lead, type Message, type Plugin } from '@/lib/api';

type Go = (tab: 'Customers' | 'Emails' | 'Business info' | 'Features') => void;
type Data = { leads: Lead[]; convs: Conv[]; msgs: Message[]; plugins: Plugin[]; docs: Docs; siteKey: string | null };

const WEEK = 7 * 86400;
const MINUTES_SAVED_PER_CHAT = 3; // a rough, stated assumption: time to answer a routine enquiry by hand
const ago = (t: number) => { const m = Math.max(1, Math.round((Date.now() / 1000 - t) / 60)); return m < 60 ? `${m} min ago` : m < 1440 ? `${Math.round(m / 60)} h ago` : `${Math.round(m / 1440)} d ago`; };

export default function Home({ go }: { go: Go }) {
  const [d, setD] = useState<Data | null>(null);
  const [err, setErr] = useState('');
  useEffect(() => {
    Promise.all([
      api<Lead[]>('GET', '/leads'), api<Conv[]>('GET', '/conversations'), api<Message[]>('GET', '/messages'),
      api<Plugin[]>('GET', '/plugins'), api<Docs>('GET', '/documents'),
      api<{ key: string | null }>('GET', '/channels/web').catch(() => ({ key: null })),
    ]).then(([leads, convs, msgs, plugins, docs, web]) => setD({ leads, convs, msgs, plugins, docs, siteKey: web.key }))
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

      <section aria-label="This week" className="grid">
        <Stat n={week.length} label="Customer chats this week" />
        <Stat n={newLeads.length} label="New leads this week" hint="Name and phone captured" />
        <Stat n={waitingPeople.length} label="Waiting for a person" />
        <Stat n={Math.round((week.length * MINUTES_SAVED_PER_CHAT) / 60 * 10) / 10} label="Hours of replies handled" hint={`Estimate: ${MINUTES_SAVED_PER_CHAT} min per chat`} />
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
  return <div className="card"><div style={{ fontSize: 30, fontWeight: 650 }}>{n}</div><div>{label}</div>{hint && <div className="muted" style={{ fontSize: 13 }}>{hint}</div>}</div>;
}
