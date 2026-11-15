'use client';
import { useCallback, useEffect, useState } from 'react';
import { api, type Connection } from '@/lib/api';

const STATUS: Record<string, [string, string]> = { connected: ['Connected', 'ok'], needs_reauth: ['Needs reconnecting', 'bad'], error: ['Failing', 'bad'], not_connected: ['Not connected', ''] };
const ago = (t?: number | null) => { if (!t) return 'never'; const m = Math.max(1, Math.round((Date.now() / 1000 - t) / 60)); return m < 60 ? `${m} min ago` : m < 1440 ? `${Math.round(m / 60)} h ago` : `${Math.round(m / 1440)} d ago`; };
const WHAT: Record<string, string> = { microsoft365: 'Reads new Outlook mail, drafts replies for your approval and sends them from your own mailbox.', xero: 'Reads overdue invoices, prepares payment reminders and leaves a note on the invoice when one is sent. Your records stay in Xero.' };

export default function Integrations({ isAdmin, flash }: { isAdmin: boolean; flash: { connected?: string; error?: string } }) {
  const [rows, setRows] = useState<Connection[] | null>(null); const [msg, setMsg] = useState(flash.error ?? (flash.connected ? 'Connected. The first sync starts within 15 minutes.' : '')); const [isErr, setIsErr] = useState(!!flash.error); const [busy, setBusy] = useState('');
  const load = useCallback(() => api<Connection[]>('GET', '/connections').then(setRows).catch((e: Error) => { setIsErr(true); setMsg(e.message); }), []);
  useEffect(() => { load(); const t = setInterval(load, 20000); return () => clearInterval(t); }, [load]);

  async function run(c: Connection, what: 'start' | 'sync' | 'disconnect') {
    setBusy(c.provider + what); setMsg(''); setIsErr(false);
    try {
      if (what === 'start') { const r = await api<{ url: string }>('POST', `/connections/${c.provider}/start`); window.location.href = r.url; return; }
      if (what === 'sync') { await api('POST', `/connections/${c.provider}/sync`); setMsg('Synced.'); }
      else { await api('DELETE', `/connections/${c.provider}`); setMsg('Disconnected. Stored credentials were deleted.'); }
      await load();
    } catch (e) { setIsErr(true); setMsg((e as Error).message); await load(); } finally { setBusy(''); }
  }
  return (
    <div className="stack">
      <p className="muted">Hivemate works on top of the software you already use. Nothing is moved or replaced. Credentials are stored encrypted, never in your business data.</p>
      {msg && <p className={isErr ? 'err' : 'ok'} role={isErr ? 'alert' : 'status'}>{msg}</p>}
      <div className="grid">
        {rows?.map((c) => {
          const [label, tone] = STATUS[c.status] ?? [c.status, ''];
          return (
            <article key={c.provider} className="card stack">
              <div className="row" style={{ justifyContent: 'space-between' }}><h3>{c.label}</h3><span className={`tag ${tone}`}>{label}</span></div>
              <span className="muted">{WHAT[c.provider]}</span>
              {c.connected && <div className="stack" style={{ gap: 4 }}>
                <span>Account: <strong>{c.account}</strong></span>
                <span>Last successful sync: <strong>{ago(c.lastSyncAt)}</strong> {c.lastSyncStatus === 'failed' && <span className="tag bad">last attempt failed</span>}</span>
                {c.failedEvents > 0 && <span>Failed deliveries: <strong>{c.failedEvents}</strong></span>}
                {c.lastError && <span className="err">{c.lastError}</span>}
                <span className="muted">Can write: {c.writes.map((w) => w.replace(/_/g, ' ')).join(', ')}</span>
              </div>}
              {!c.available && !c.connected && <p className="err">Not set up on this Hivemate yet: the operator must register the app first (see docs/GO-LIVE.md).</p>}
              {isAdmin && <div className="row">
                {(!c.connected || c.status === 'needs_reauth') && <button className="btn primary" disabled={!c.available || !!busy} onClick={() => run(c, 'start')}>{c.status === 'needs_reauth' ? 'Reconnect' : 'Connect'}</button>}
                {c.connected && c.status !== 'needs_reauth' && <button className="btn" disabled={!!busy} onClick={() => run(c, 'sync')}>{c.status === 'error' ? 'Retry now' : 'Sync now'}</button>}
                {c.connected && <button className="btn danger" disabled={!!busy} onClick={() => run(c, 'disconnect')}>Disconnect</button>}
              </div>}
            </article>
          );
        })}
      </div>
      <section className="card"><h3>Also connected without a login</h3><p className="muted">Website chat and WhatsApp are set up under Conversations. Gmail works through a draft-only script in your own Google account.</p></section>
    </div>
  );
}
