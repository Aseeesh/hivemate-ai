'use client';
import { useState, type FormEvent } from 'react';
import { api, type AskAnswer } from '@/lib/api';

const EXAMPLES = ['How many enquiries did we get this month?', "Which customers haven't received a reply?", 'How many invoices are overdue?', 'What are the main customer complaints?', 'How many hours did automation save?', 'Which automation saved the most time?'];

export default function Ask() {
  const [q, setQ] = useState(''); const [a, setA] = useState<AskAnswer | null>(null); const [busy, setBusy] = useState(false); const [err, setErr] = useState('');
  async function ask(text: string) {
    if (!text.trim()) return; setBusy(true); setErr(''); setQ(text);
    try { setA(await api<AskAnswer>('POST', '/ask', { question: text })); } catch (e) { setErr((e as Error).message); } finally { setBusy(false); }
  }
  return (
    <div className="stack">
      <section className="card stack">
        <h2>Ask about your business</h2>
        <p className="muted">Answers are calculated from your records, and each one shows how and which records it used. If a question cannot be calculated, it says so instead of guessing.</p>
        <form className="row" onSubmit={(e: FormEvent) => { e.preventDefault(); ask(q); }}><input style={{ flex: 1, minWidth: 240 }} value={q} onChange={(e) => setQ(e.target.value)} placeholder="e.g. How many invoices are overdue?" maxLength={300} aria-label="Your question" /><button className="btn primary" disabled={busy}>Ask</button></form>
        <div className="row">{EXAMPLES.map((x) => <button key={x} className="btn" disabled={busy} onClick={() => ask(x)}>{x}</button>)}</div>
      </section>
      {err && <p className="err" role="alert">{err}</p>}
      {a && <section className="card stack" aria-live="polite">
        <h3>{a.answer}</h3>
        {a.calculation && <p className="muted" style={{ margin: 0 }}><strong>How it was worked out:</strong> {a.calculation}</p>}
        {a.examples && <ul>{a.examples.map((x) => <li key={x}>{x}</li>)}</ul>}
        {a.sources.length > 0 && <details open><summary>Records used ({a.sources.length})</summary><ul>{a.sources.map((s) => <li key={s.type + s.id}><span className="src">{s.type}</span> {s.label || s.id}</li>)}</ul></details>}
      </section>}
    </div>
  );
}
