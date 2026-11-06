'use client';
import { useCallback, useEffect, useState } from 'react';
import { CountUp, DayBars, RankBars, Segments } from '@/components/charts';
import { api, type PlatformDetail, type PlatformOverview, type PlatformTenant } from '@/lib/api';

const ago = (s: number) => {
  if (!s) return 'never';
  const d = Math.max(0, Date.now() / 1000 - s);
  return d < 90 ? 'just now' : d < 5400 ? `${Math.round(d / 60)} min ago` : d < 129600 ? `${Math.round(d / 3600)} h ago` : `${Math.round(d / 86400)} d ago`;
};
const kb = (n: number) => (n > 1048576 ? `${(n / 1048576).toFixed(1)} MB` : `${Math.max(1, Math.round(n / 1024))} KB`);

function Detail({ id, onClose }: { id: string; onClose: () => void }) {
  const [d, setD] = useState<PlatformDetail>(); const [err, setErr] = useState('');
  useEffect(() => { setD(undefined); api<PlatformDetail>('GET', `/platform/tenants/${id}`).then(setD).catch((e: Error) => setErr(e.message)); }, [id]);
  return (
    <section className="card stack" aria-live="polite">
      <div className="row" style={{ justifyContent: 'space-between' }}>
        <h2 style={{ margin: 0 }}>{d?.name ?? 'Loading…'}</h2><button className="btn" onClick={onClose}>Close</button>
      </div>
      {err && <p className="err">{err}</p>}
      {d && <>
        <p className="muted">Viewing this business is recorded in its audit log. Customer messages, lead details and settings values are never shown here.</p>
        <div className="grid">
          <DayBars title="Chats per day" unit="chats" data={d.daily.map((x) => ({ day: x.day, v: x.conversations }))} />
          <DayBars title="Leads per day" unit="leads" color="var(--s3)" data={d.daily.map((x) => ({ day: x.day, v: x.leads }))} />
        </div>
        <Segments title="Enquiry outcomes" empty="No enquiries yet." parts={[{ label: 'Lead captured', value: d.leadsComplete, color: 'var(--s3)' }, { label: 'In progress', value: Math.max(0, d.leads - d.leadsComplete - d.handoffs), color: 'var(--s1)' }, { label: 'Handed to a person', value: d.handoffs, color: 'var(--s2)' }]} />
        <div className="grid">
          <div><h3>Users</h3>{d.userList.map((u) => <div key={u.email}>{u.email} <span className="tag">{u.role}</span></div>)}</div>
          <div><h3>Plugins</h3>{d.pluginList.length ? d.pluginList.map((p) => <div key={p.pluginId}><span className="mono">{p.pluginId}</span> <span className="muted">v{p.version}</span></div>) : <span className="muted">none installed</span>}</div>
          <div><h3>Website</h3>{d.origins.length ? d.origins.map((o) => <div key={o} className="mono">{o}</div>) : <span className="muted">{d.channels.includes('web') ? 'chat live, any website allowed' : 'no website chat'}</span>}<div className="muted" style={{ marginTop: 6 }}>Channels: {d.channels.length ? d.channels.join(', ') : 'none'}</div></div>
          <div><h3>Knowledge ({d.documents.count} files, {kb(d.documents.bytes)})</h3>{d.documentList.length ? d.documentList.slice(0, 8).map((f) => <div key={f.name} className="mono">{f.name}</div>) : <span className="muted">no documents</span>}</div>
          <div><h3>Activity</h3><div>{d.conversations} conversations · {d.handoffs} handed off</div><div>{d.leadsComplete}/{d.leads} leads complete</div><div>{d.messages} emails · {d.messagesHeld} awaiting approval</div></div>
        </div>
        <h3>Recent actions</h3>
        <table><thead><tr><th>Time</th><th>Action</th></tr></thead><tbody>
          {d.recentAudit.map((a, i) => <tr key={i}><td className="mono">{new Date(a.at ?? 0).toLocaleString('en-NZ')}</td><td className="mono">{a.action}</td></tr>)}
        </tbody></table>
      </>}
    </section>
  );
}

export default function PlatformConsole() {
  const [ov, setOv] = useState<PlatformOverview>(); const [rows, setRows] = useState<PlatformTenant[]>([]);
  const [error, setError] = useState(''); const [open, setOpen] = useState<string>(); const [q, setQ] = useState(''); const [loading, setLoading] = useState(false);
  const load = useCallback(() => {
    setLoading(true); setError('');
    Promise.all([api<PlatformOverview>('GET', '/platform/overview'), api<{ tenants: PlatformTenant[] }>('GET', '/platform/tenants')])
      .then(([o, t]) => { setOv(o); setRows(t.tenants); }).catch((e: Error) => setError(e.message)).finally(() => setLoading(false));
  }, []);
  useEffect(load, [load]);
  const shown = rows.filter((r) => `${r.name} ${r.tenantId}`.toLowerCase().includes(q.toLowerCase()));
  const tiles: [string, string | number, string?][] = ov ? [
    ['Businesses', ov.tenants], ['Active in 24 h', ov.activeLast24h], ['Users', ov.users], ['Conversations', ov.conversations],
    ['Leads complete', `${ov.leadsComplete}/${ov.leads}`], ['Handed to a person', ov.handoffs], ['Emails awaiting approval', ov.messagesHeld],
  ] : [];
  return (
    <div className="stack">
      {error && <p className="err" role="alert">{error}</p>}
      <p className="muted">Read-only view across all businesses. Counts and status only: no customer content.</p>
      <div className="grid" style={{ gridTemplateColumns: 'repeat(auto-fill,minmax(150px,1fr))' }}>
        {tiles.map(([k, v]) => <div key={k} className="card"><div className="muted" style={{ fontSize: 12 }}>{k}</div><div className="hero-num" style={{ fontSize: 26 }}>{typeof v === 'number' ? <CountUp value={v} /> : v}</div></div>)}
      </div>
      {ov && <>
        <div className="grid" style={{ gridTemplateColumns: 'repeat(auto-fit,minmax(340px,1fr))' }}>
          <DayBars title="Chats per day, all businesses" unit="chats" data={ov.daily.map((x) => ({ day: x.day, v: x.conversations }))} />
          <RankBars title="Most active businesses (chats)" unit="chats" rows={[...rows].sort((a, b) => b.conversations - a.conversations).slice(0, 8).map((t) => ({ id: t.tenantId, label: t.name || t.tenantId, value: t.conversations }))} onPick={setOpen} />
        </div>
        <Segments title="All enquiries across the platform" empty="No enquiries yet." parts={[{ label: 'Lead captured', value: ov.leadsComplete, color: 'var(--s3)' }, { label: 'In progress', value: Math.max(0, ov.leads - ov.leadsComplete - ov.handoffs), color: 'var(--s1)' }, { label: 'Handed to a person', value: ov.handoffs, color: 'var(--s2)' }]} />
      </>}
      {ov && <p className="muted">Plugin installs: {Object.entries(ov.pluginInstalls).map(([k, v]) => `${k} ×${v}`).join(' · ') || 'none'}{ov.truncated ? ' · (partial: table too large for a full scan)' : ''}</p>}
      {open && <Detail id={open} onClose={() => setOpen(undefined)} />}
      <section className="card stack">
        <div className="row"><input placeholder="Search businesses" aria-label="Search businesses" value={q} onChange={(e) => setQ(e.target.value)} style={{ maxWidth: 280 }} />
          <button className="btn" onClick={load} disabled={loading}>{loading ? 'Refreshing…' : 'Refresh'}</button><span className="muted">{shown.length} shown</span></div>
        <div style={{ overflowX: 'auto' }}>
          <table><thead><tr><th>Business</th><th>Plugins</th><th>Users</th><th>Conversations</th><th>Leads</th><th>Held</th><th>Last activity</th></tr></thead><tbody>
            {shown.map((t) => (
              <tr key={t.tenantId}>
                <td><button className="btn" onClick={() => setOpen(t.tenantId)} aria-label={`View ${t.name}`}>{t.name || t.tenantId}</button></td>
                <td className="mono">{t.plugins.length}</td><td>{t.users}</td><td>{t.conversations}</td><td>{t.leadsComplete}/{t.leads}</td>
                <td>{t.messagesHeld ? <span className="tag hold">{t.messagesHeld}</span> : '–'}</td><td className="muted">{ago(t.lastActivity)}</td>
              </tr>
            ))}
            {!shown.length && <tr><td colSpan={7} className="muted">No businesses match.</td></tr>}
          </tbody></table>
        </div>
      </section>
    </div>
  );
}
