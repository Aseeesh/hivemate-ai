'use client';
import { useCallback, useEffect, useState } from 'react';
import { api, type Deal } from '@/lib/api';
import { Icon } from '@/components/icons';

const COLS: { id: string; label: string; color: string; stages: string[] }[] = [
  { id: 'new', label: 'New', color: 'var(--s1)', stages: ['new'] },
  { id: 'responded', label: 'Replied', color: 'var(--s3)', stages: ['responded', 'followed_up'] },
  { id: 'quote_sent', label: 'Quote sent', color: 'var(--amber)', stages: ['quote_sent'] },
  { id: 'won', label: 'Won', color: 'var(--fern)', stages: ['won'] },
  { id: 'cold', label: 'Cold or lost', color: 'var(--muted)', stages: ['cold', 'lost'] },
];
const CH: Record<string, string> = { email: 'mail', web: 'chat', whatsapp: 'phone' };
const ago = (t?: number) => { if (!t) return ''; const m = Math.max(1, Math.round((Date.now() / 1000 - t) / 60)); return m < 60 ? `${m} min` : m < 1440 ? `${Math.round(m / 60)} h` : `${Math.round(m / 1440)} d`; };

export default function PipelineBoard() {
  const [deals, setDeals] = useState<Deal[] | null>(null); const [msg, setMsg] = useState(''); const [busy, setBusy] = useState('');
  const load = useCallback(() => api<{ deals: Deal[] }>('GET', '/deals').then((r) => setDeals(r.deals)).catch((e: Error) => setMsg(e.message)), []);
  useEffect(() => { load(); }, [load]);
  async function move(d: Deal, stage: string) { setBusy(d.dealId); setMsg(''); try { await api('POST', `/deals/${d.dealId}/stage`, { stage }); await load(); } catch (e) { setMsg((e as Error).message); } finally { setBusy(''); } }
  if (!deals) return <p className="muted">{msg || 'Loading…'}</p>;
  return (
    <div className="stack">
      {msg && <p className="err" role="alert">{msg}</p>}
      {!deals.length && <p className="muted">No enquiries tracked yet. They appear here once a customer shares a name, phone or email.</p>}
      <div className="board" role="list" aria-label="Enquiry pipeline">
        {COLS.map((c) => {
          const rows = deals.filter((d) => c.stages.includes(d.stage));
          return (
            <section key={c.id} className="col" role="listitem" style={{ ['--c' as string]: c.color }} aria-label={`${c.label}: ${rows.length}`}>
              <h3>{c.label}<span>{rows.length}</span></h3>
              {rows.map((d) => (
                <article key={d.dealId} className="dealcard">
                  <div className="row" style={{ gap: 6, justifyContent: 'space-between' }}><strong>{d.name || d.email || 'Unknown'}</strong><span className="muted"><Icon name={CH[d.channel ?? ''] ?? 'chat'} size={14} /></span></div>
                  <span className="muted">{d.need || 'Enquiry'}</span>
                  <span className="row" style={{ gap: 6 }}>
                    {d.awaiting === 'business' && d.stage !== 'won' && d.stage !== 'lost' && <span className="tag bad">waiting for you</span>}
                    {d.stage === 'followed_up' && <span className="tag hold">followed up ×{d.followUpCount}</span>}
                    {d.stage === 'cold' && <span className="tag">cold</span>}{d.stage === 'lost' && <span className="tag">lost</span>}
                    <span className="muted" style={{ fontSize: 12 }}>{ago(d.lastInboundAt)} ago</span></span>
                  {!['won', 'lost'].includes(d.stage) && <div className="acts">
                    {d.stage !== 'quote_sent' && <button disabled={!!busy} onClick={() => move(d, 'quote_sent')}>Quote sent</button>}
                    <button disabled={!!busy} onClick={() => move(d, 'won')}>Won</button><button disabled={!!busy} onClick={() => move(d, 'lost')}>Lost</button></div>}
                </article>
              ))}
            </section>
          );
        })}
      </div>
    </div>
  );
}
