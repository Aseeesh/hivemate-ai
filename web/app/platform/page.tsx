'use client';
import { useRouter } from 'next/navigation';
import { useEffect, useState } from 'react';
import { signOut, idToken } from '@/lib/auth';
import { api, type Me } from '@/lib/api';
import PlatformConsole from '@/components/PlatformConsole';

/** Operator console. Separate from the business dashboard: it is only usable by members of the platform-admins group. */
export default function Platform() {
  const router = useRouter();
  const [me, setMe] = useState<Me | null>(null);
  const [error, setError] = useState('');
  useEffect(() => {
    idToken().then((t) => {
      if (!t) return router.replace('/');
      api<Me>('GET', '/me').then((m) => (m.user.platform ? setMe(m) : router.replace('/dashboard/'))).catch((e: Error) => setError(e.message));
    });
  }, [router]);
  return (
    <main className="wrap">
      <header className="bar">
        <div><h1>Hivemate platform</h1><span className="muted">{me ? `${me.user.email} · platform admin` : 'Loading…'}</span></div>
        <div className="row">
          <a className="btn" href="/dashboard/">My business</a>
          <button className="btn" onClick={() => { signOut(); router.replace('/'); }}>Sign out</button>
        </div>
      </header>
      {error && <p className="err" role="alert">{error}</p>}
      {me && <PlatformConsole />}
    </main>
  );
}
