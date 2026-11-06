'use client';
import { useCallback, useEffect, useRef, useState } from 'react';
import { api, type Docs } from '@/lib/api';

type Upload = { key: string; upload: { url: string; fields: Record<string, string> } };

export default function Documents({ isAdmin }: { isAdmin: boolean }) {
  const [docs, setDocs] = useState<Docs | null>(null);
  const [msg, setMsg] = useState(''); const [busy, setBusy] = useState(false);
  const file = useRef<HTMLInputElement>(null); const [aud, setAud] = useState<'public' | 'internal'>('public');
  const load = useCallback(() => api<Docs>('GET', '/documents').then(setDocs).catch((e: Error) => setMsg(e.message)), []);
  useEffect(() => { load(); }, [load]);
  // While an ingestion job is running, poll until it finishes.
  useEffect(() => {
    const s = docs?.lastSync?.status;
    if (s && s !== 'COMPLETE' && s !== 'FAILED') { const t = setTimeout(load, 4000); return () => clearTimeout(t); }
  }, [docs, load]);

  async function upload() {
    const f = file.current?.files?.[0]; if (!f) return;
    setBusy(true); setMsg('');
    try {
      const { upload: u } = await api<Upload>('POST', '/documents', { filename: f.name, audience: aud });
      const form = new FormData();
      Object.entries(u.fields).forEach(([k, v]) => form.append(k, v));
      form.append('file', f); // must be last
      const res = await fetch(u.url, { method: 'POST', body: form });
      if (!res.ok) throw new Error(`Upload failed (${res.status}). Files must be under 10 MB.`);
      if (file.current) file.current.value = '';
      setMsg('Uploaded. Click "Sync knowledge" so the assistant can use it.'); load();
    } catch (e) { setMsg((e as Error).message); } finally { setBusy(false); }
  }
  async function retag(name: string, audience: 'public' | 'internal') { setBusy(true); try { await api('PUT', `/documents/${encodeURIComponent(name)}`, { audience }); await load(); setMsg('Changed. Press Sync knowledge to apply it.'); } catch (e) { setMsg((e as Error).message); } finally { setBusy(false); } }
  async function sync() { setBusy(true); try { await api('POST', '/documents/sync'); setMsg('Sync started'); await load(); } catch (e) { setMsg((e as Error).message); } finally { setBusy(false); } }
  async function remove(name: string) { setBusy(true); try { await api('DELETE', `/documents/${encodeURIComponent(name)}`); await load(); setMsg('Deleted. Sync again to remove it from search.'); } catch (e) { setMsg((e as Error).message); } finally { setBusy(false); } }

  const s = docs?.lastSync;
  return (
    <div className="stack">
      <section className="card stack">
        <h2>Business knowledge</h2>
        <p className="muted">FAQs, price lists and policies the assistant uses. <strong>Customers only ever get answers from files marked &quot;Customers can see&quot;.</strong> Files marked &quot;Internal&quot; (costs, staff notes, procedures) are available only to you, in Admin preview. Allowed: pdf, txt, md, html, csv, docx up to 10 MB.</p>
        {isAdmin && <div className="row">
          <input ref={file} type="file" accept=".pdf,.txt,.md,.html,.csv,.docx" style={{ width: 'auto' }} />
          <select aria-label="Who can see this file" value={aud} onChange={(e) => setAud(e.target.value as 'public' | 'internal')} style={{ width: 'auto' }}><option value="public">Customers can see</option><option value="internal">Internal only (staff)</option></select>
          <button className="btn primary" disabled={busy} onClick={upload}>Upload</button>
          <button className="btn" disabled={busy} onClick={sync}>Sync knowledge</button>
        </div>}
        <div className="row">
          <span className="muted">Last sync:</span>
          {s ? <span className={`tag ${s.status === 'COMPLETE' ? 'ok' : s.status === 'FAILED' ? 'bad' : 'hold'}`}>{s.status}</span> : <span className="tag">never</span>}
          <span role="status" className="muted">{msg}</span>
        </div>
      </section>
      <section className="card">
        <table><thead><tr><th>File</th><th>Who sees it</th><th>Size</th><th>Uploaded</th><th /></tr></thead><tbody>
          {docs?.documents.map((d) => (
            <tr key={d.name}><td>{d.name}</td><td><span className={`tag ${d.audience === 'internal' ? 'hold' : 'ok'}`}>{d.audience === 'internal' ? 'internal only' : 'customers'}</span>{isAdmin && <> <button className="btn" disabled={busy} onClick={() => retag(d.name, d.audience === 'internal' ? 'public' : 'internal')}>{d.audience === 'internal' ? 'Share with customers' : 'Make internal'}</button></>}</td><td>{(d.size / 1024).toFixed(1)} KB</td><td>{new Date(d.modified).toLocaleString('en-NZ')}</td>
              <td>{isAdmin && <button className="btn danger" disabled={busy} onClick={() => remove(d.name)}>Delete</button>}</td></tr>
          ))}
          {docs && !docs.documents.length && <tr><td colSpan={5} className="muted">No documents yet.</td></tr>}
        </tbody></table>
      </section>
    </div>
  );
}
