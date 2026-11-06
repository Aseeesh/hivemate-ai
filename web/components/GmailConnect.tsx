'use client';
import { useEffect, useState } from 'react';
import { api } from '@/lib/api';
import { gmailScript } from '@/lib/gmailScript';

/** Optional, additive: the owner keeps using Gmail exactly as now; Hivemate only leaves suggested replies in their Drafts. */
export default function GmailConnect({ isAdmin }: { isAdmin: boolean }) {
  const [connected, setConnected] = useState<boolean>(); const [token, setToken] = useState(''); const [msg, setMsg] = useState(''); const [copied, setCopied] = useState(false);
  const url = process.env.NEXT_PUBLIC_PUBLIC_CHAT_URL ?? '';
  useEffect(() => { if (isAdmin) api<{ connected: boolean }>('GET', '/integrations/email').then((s) => setConnected(s.connected)).catch(() => undefined); }, [isAdmin]);
  if (!isAdmin) return null;
  async function create() {
    setMsg('');
    try { const r = await api<{ token: string }>('PUT', '/integrations/email'); setToken(r.token); setConnected(true); }
    catch (e) { setMsg((e as Error).message); }
  }
  async function disconnect() {
    try { await api('DELETE', '/integrations/email'); setToken(''); setConnected(false); setMsg('Disconnected. Any script using the old key stops working.'); } catch (e) { setMsg((e as Error).message); }
  }
  const script = token ? gmailScript(url, token) : '';
  return (
    <details className="card" open={!!token}><summary><strong>Gmail replies, in your own Gmail</strong> <span className={`tag ${connected ? 'ok' : ''}`}>{connected ? 'connected' : 'optional'}</span></summary>
      <div className="stack" style={{ marginTop: 12 }}>
        <p className="muted" style={{ margin: 0 }}>Keep using Gmail exactly as you do now. Hivemate reads new customer enquiries and leaves a <strong>suggested reply in your Drafts</strong>. You read it, edit it and press Send. It never sends anything itself, and emails it is unsure about (complaints, refunds, prices) are labelled &quot;Hivemate-needs-you&quot; with no draft.</p>
        <div className="row">
          <button className="btn primary" onClick={create}>{connected ? 'Create a new key (replaces the old one)' : 'Create my key'}</button>
          {connected && <button className="btn danger" onClick={disconnect}>Disconnect</button>}
          <span role="status" className="muted">{msg}</span>
        </div>
        {token && <>
          <ol style={{ margin: 0, paddingLeft: 20 }}>
            <li>Open <span className="mono">script.google.com</span> signed in to the Gmail you use for the business and press <strong>New project</strong>.</li>
            <li>Delete what is there, paste the script below, and press <strong>Save</strong>.</li>
            <li>Press <strong>Run</strong> once and allow access. Google will say the app is unverified; it is your own script in your own account.</li>
            <li>Add a trigger: <strong>run</strong>, time-driven, every 10 minutes.</li>
          </ol>
          <label>Your script (the key inside is shown only now; keep it private)<textarea readOnly rows={10} value={script} onFocus={(e) => e.currentTarget.select()} className="mono" /></label>
          <div className="row"><button className="btn" onClick={() => { navigator.clipboard.writeText(script).then(() => setCopied(true)).catch(() => setCopied(false)); }}>{copied ? 'Copied' : 'Copy script'}</button></div>
        </>}
      </div>
    </details>
  );
}
