'use client';
import { useEffect, useState } from 'react';
import { api, type Audit } from '@/lib/api';

export default function AuditLog() {
  const [rows, setRows] = useState<Audit[]>([]); const [error, setError] = useState('');
  useEffect(() => { api<Audit[]>('GET', '/audit').then(setRows).catch((e: Error) => setError(e.message)); }, []);
  return (
    <section className="card">
      {error && <p className="err">{error}</p>}
      <table><thead><tr><th>Time</th><th>Actor</th><th>Action</th><th>Detail</th></tr></thead><tbody>
        {rows.map((r) => (
          <tr key={r.SK}><td className="mono">{new Date(r.at).toLocaleString('en-NZ')}</td><td>{r.actor.startsWith('plugin:') ? r.actor : 'user'}</td>
            <td className="mono">{r.action}</td><td className="mono muted">{Object.entries(r.detail).map(([k, v]) => `${k}=${String(v)}`).join(' ')}</td></tr>
        ))}
      </tbody></table>
    </section>
  );
}
