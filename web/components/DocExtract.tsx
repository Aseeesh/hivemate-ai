'use client';
import { useCallback, useEffect, useRef, useState } from 'react';
import { api, type ExtractedDoc } from '@/lib/api';

type Upload = { key: string; upload: { url: string; fields: Record<string, string> } };
const when = (t: number) => new Date(t * 1000).toLocaleString('en-NZ', { day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit' });

export default function DocExtract() {
  const [docs, setDocs] = useState<ExtractedDoc[]>([]); const file = useRef<HTMLInputElement>(null); const [msg, setMsg] = useState(''); const [isErr, setIsErr] = useState(false); const [busy, setBusy] = useState(false);
  const load = useCallback(() => api<{ documents: ExtractedDoc[] }>('GET', '/extract').then((r) => setDocs(r.documents)).catch((e: Error) => { setIsErr(true); setMsg(e.message); }), []);
  useEffect(() => { load(); }, [load]);
  async function run() {
    const f = file.current?.files?.[0]; if (!f) return; setBusy(true); setMsg(''); setIsErr(false);
    try {
      const { key, upload: u } = await api<Upload>('POST', '/extract/upload', { filename: f.name });
      const form = new FormData(); Object.entries(u.fields).forEach(([k, v]) => form.append(k, v)); form.append('file', f);
      const res = await fetch(u.url, { method: 'POST', body: form }); if (!res.ok) throw new Error(`Upload failed (${res.status}). Files must be under 10 MB.`);
      await api('POST', '/extract', { key }); if (file.current) file.current.value = ''; setMsg('Read. Check the figures below, then approve it in the Work Queue.'); await load();
    } catch (e) { setIsErr(true); setMsg((e as Error).message); } finally { setBusy(false); }
  }
  return (
    <div className="stack">
      <section className="card stack">
        <h2>Invoices and receipts</h2>
        <p className="muted">Upload a supplier invoice or receipt (photo or one-page PDF). Hivemate reads the supplier, number, dates, GST and total, checks them, and sends them to your Work Queue for approval. Nothing is posted to your accounts.</p>
        <div className="row"><input ref={file} type="file" accept=".pdf,.png,.jpg,.jpeg,.tif,.tiff" style={{ maxWidth: 320 }} aria-label="Invoice or receipt" /><button className="btn primary" disabled={busy} onClick={run}>{busy ? 'Reading…' : 'Read document'}</button></div>
        {msg && <p className={isErr ? 'err' : 'ok'} role={isErr ? 'alert' : 'status'}>{msg}</p>}
      </section>
      {docs.map((d) => (
        <article key={d.docId} className="card stack">
          <div className="row" style={{ justifyContent: 'space-between' }}><h3>{d.supplier || d.fileName} {d.invoiceNumber}</h3><span className={`tag ${d.status === 'approved' ? 'ok' : d.status === 'rejected' ? 'bad' : 'hold'}`}>{d.status.replace('_', ' ')}</span></div>
          <table><tbody>
            <tr><th>Invoice date</th><td>{d.invoiceDate ?? '—'}</td><th>Due</th><td>{d.dueDate ?? '—'}</td></tr>
            <tr><th>Subtotal</th><td>{d.subtotal != null ? `$${d.subtotal.toFixed(2)}` : '—'}</td><th>GST</th><td>{d.gst != null ? `$${d.gst.toFixed(2)}` : '—'}</td></tr>
            <tr><th>Total</th><td>{d.total != null ? `$${d.total.toFixed(2)}` : '—'}</td><th>Read confidence</th><td>{d.confidence}%</td></tr></tbody></table>
          {d.flags.length ? <div>{d.flags.map((f) => <p key={f} className="err" style={{ margin: 0 }}>⚠ {f}</p>)}</div> : <p className="ok">No problems found.</p>}
          <span className="muted">{when(d.createdAt)} · {d.fileName}</span>
        </article>
      ))}
    </div>
  );
}
