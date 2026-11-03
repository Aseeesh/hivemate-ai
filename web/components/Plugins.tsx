'use client';
import { useCallback, useEffect, useState } from 'react';
import { api, type Plugin } from '@/lib/api';

function Editor({ p, isAdmin, onSaved }: { p: Plugin; isAdmin: boolean; onSaved: () => void }) {
  const initial = Object.fromEntries(Object.entries(p.configurationSchema).map(([k, s]) => [k, p.config?.[k] ?? s.default]));
  const [cfg, setCfg] = useState<Record<string, unknown>>(initial);
  const [msg, setMsg] = useState(''); const [busy, setBusy] = useState(false);

  async function run(fn: () => Promise<unknown>, ok: string) {
    setBusy(true); setMsg('');
    try { await fn(); setMsg(ok); onSaved(); } catch (e) { setMsg((e as Error).message); } finally { setBusy(false); }
  }
  const save = () => run(() => api('PUT', `/plugins/${p.pluginId}`, { config: cfg }), 'Saved');
  const remove = () => run(() => api('DELETE', `/plugins/${p.pluginId}`), 'Removed');

  return (
    <div className="stack">
      {Object.entries(p.configurationSchema).map(([key, s]) => {
        const v = cfg[key];
        const set = (x: unknown) => setCfg({ ...cfg, [key]: x });
        if (s.type === 'boolean') return <label key={key} className="row"><input style={{ width: 'auto' }} type="checkbox" disabled={!isAdmin} checked={!!v} onChange={(e) => set(e.target.checked)} />{key}</label>;
        if (s.type === 'number') return <label key={key}>{key}<input type="number" step="0.05" disabled={!isAdmin} value={Number(v)} onChange={(e) => set(Number(e.target.value))} /></label>;
        if (s.type === 'array') return <label key={key}>{key} (comma separated)<input disabled={!isAdmin} value={(v as string[]).join(', ')} onChange={(e) => set(e.target.value.split(',').map((x) => x.trim()).filter(Boolean))} /></label>;
        return <label key={key}>{key}<input disabled={!isAdmin} value={String(v ?? '')} onChange={(e) => set(e.target.value)} /></label>;
      })}
      {isAdmin && <div className="row">
        <button className="btn primary" disabled={busy} onClick={save}>{p.installed ? 'Save settings' : 'Install'}</button>
        {p.installed && <button className="btn danger" disabled={busy} onClick={remove}>Remove</button>}
        <span className="muted" role="status">{msg}</span>
      </div>}
    </div>
  );
}

export default function Plugins({ isAdmin }: { isAdmin: boolean }) {
  const [plugins, setPlugins] = useState<Plugin[]>([]); const [error, setError] = useState('');
  const load = useCallback(() => api<Plugin[]>('GET', '/plugins').then(setPlugins).catch((e: Error) => setError(e.message)), []);
  useEffect(() => { load(); }, [load]);

  return (
    <div className="grid">
      {error && <p className="err">{error}</p>}
      {plugins.map((p) => (
        <section key={p.pluginId} className="card stack">
          <div className="row" style={{ justifyContent: 'space-between' }}>
            <h3>{p.name}</h3><span className={`tag ${p.installed ? 'ok' : ''}`}>{p.installed ? 'installed' : 'not installed'}</span>
          </div>
          <p className="muted">{p.description}</p>
          <div className="row">{p.permissions.map((x) => <span key={x} className="tag">{x}</span>)}</div>
          <Editor key={p.pluginId + String(p.installed)} p={p} isAdmin={isAdmin} onSaved={load} />
        </section>
      ))}
    </div>
  );
}
