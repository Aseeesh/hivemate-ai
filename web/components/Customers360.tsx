'use client';
import { useEffect, useState } from 'react';
import { api, type CustomerDetail, type CustomerRow } from '@/lib/api';

const when = (t: number) => (t ? new Date(t * 1000).toLocaleDateString('en-NZ', { day: 'numeric', month: 'short' }) : '');

export default function Customers360() {
  const [q, setQ] = useState(''); const [rows, setRows] = useState<CustomerRow[] | null>(null); const [sel, setSel] = useState<CustomerDetail | null>(null); const [err, setErr] = useState('');
  useEffect(() => { const t = setTimeout(() => api<{ customers: CustomerRow[] }>('GET', `/customers?q=${encodeURIComponent(q)}`).then((r) => setRows(r.customers)).catch((e: Error) => setErr(e.message)), 250); return () => clearTimeout(t); }, [q]);
  const pick = (key: string) => api<CustomerDetail>('GET', `/customers/${encodeURIComponent(key)}`).then(setSel).catch((e: Error) => setErr(e.message));
  return (
    <div className="grid" style={{ gridTemplateColumns: 'repeat(auto-fit,minmax(320px,1fr))', alignItems: 'start' }}>
      <section className="card stack" aria-label="Customers">
        <label>Search by name, email or phone<input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Search customers" /></label>
        {err && <p className="err" role="alert">{err}</p>}
        {rows && !rows.length && <p className="muted">No customers yet. They appear once someone shares contact details in a chat or email.</p>}
        {rows?.map((c) => (
          <button key={c.key} className="btn" aria-pressed={sel?.key === c.key} style={{ textAlign: 'left' }} onClick={() => pick(c.key)}>
            <strong>{c.name}</strong> <span className="muted">{c.email || c.phone}</span><br /><span className="muted">{c.stage.replace('_', ' ')}{c.awaiting === 'business' ? ' · waiting for you' : ''} · {c.channels.join(', ')}</span>
          </button>
        ))}
      </section>
      <section className="card stack" aria-label="Customer detail">
        {!sel ? <p className="muted">Choose a customer to see everything in one place.</p> : <>
          <h2>{sel.name}</h2>
          <div className="muted">{[sel.email, sel.phone].filter(Boolean).join(' · ')} · <span title="How these records were joined">{sel.identity}</span></div>
          {sel.summary && <blockquote><strong>Summary</strong> <span className="src">{sel.summarySource}</span><br />{sel.summary}</blockquote>}
          <h3>Outstanding follow-ups</h3>
          {sel.outstandingFollowUps.length ? sel.outstandingFollowUps.map((f) => <div key={f.id}>• {f.title} <span className="tag">{f.status.replace('_', ' ')}</span></div>) : <p className="muted">None.</p>}
          <h3>Conversations</h3>
          {sel.conversations.length ? sel.conversations.map((c) => <div key={c.id}><span className="src">{c.source}</span> {c.turns} messages · {c.status.toLowerCase()} · {when(c.lastAt)}</div>) : <p className="muted">None.</p>}
          <h3>Emails</h3>
          {sel.emails.length ? sel.emails.map((m) => <div key={m.id}><span className="src">{m.source}</span> {m.subject || '(no subject)'} <span className="tag">{m.status.toLowerCase().replace('_', ' ')}</span> {when(m.at)}</div>) : <p className="muted">None.</p>}
          <h3>Invoices</h3>
          {sel.invoices.length ? sel.invoices.map((i) => <div key={i.id}><span className="src">{i.source}</span> {i.number} · ${i.amountDue.toFixed(2)} due {i.dueDate}{i.daysOverdue > 0 ? <span className="tag bad"> {i.daysOverdue} days overdue</span> : null}</div>) : <p className="muted">None (connect Xero under Integrations).</p>}
          <h3>Pipeline</h3>
          {sel.deals.map((d) => <div key={d.dealId}><span className="src">{d.source}</span> {d.need || 'Enquiry'} · <strong>{d.stage.replace('_', ' ')}</strong> · {d.followUpCount} follow-up(s)</div>)}
        </>}
      </section>
    </div>
  );
}
