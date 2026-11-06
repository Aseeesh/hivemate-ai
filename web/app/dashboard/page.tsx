'use client';
import { useRouter } from 'next/navigation';
import { useEffect, useState } from 'react';
import { signOut, idToken } from '@/lib/auth';
import { api, type Me } from '@/lib/api';
import Plugins from '@/components/Plugins';
import Documents from '@/components/Documents';
import Inbox from '@/components/Inbox';
import Agent from '@/components/Agent';
import AuditLog from '@/components/AuditLog';
import Home from '@/components/Home';

// Named for what the owner gets, not for how the system is built.
const TABS = ['Home', 'Customers', 'Emails', 'Business info', 'Features', 'Activity'] as const;
type Tab = (typeof TABS)[number];

export default function Dashboard() {
  const router = useRouter();
  const [me, setMe] = useState<Me | null>(null);
  const [tab, setTab] = useState<Tab>('Home');
  const [error, setError] = useState('');

  useEffect(() => {
    idToken().then((t) => {
      if (!t) return router.replace('/');
      api<Me>('GET', '/me').then(setMe).catch((e: Error) => setError(e.message));
    });
  }, [router]);

  const isAdmin = me?.user.role === 'admin';
  return (
    <main className="wrap">
      <header className="bar">
        <div>
          <h1>{me?.tenant.name ?? 'Hivemate'}</h1>
          <span className="muted">{me ? `${me.user.email} · ${me.user.role} · ${me.tenant.timezone}` : 'Loading…'}</span>
        </div>
        <div className="row">
          {me?.user.platform && <a className="btn" href="/platform/">Platform console</a>}
          <button className="btn" onClick={() => { signOut(); router.replace('/'); }}>Sign out</button>
        </div>
      </header>
      {error && <p className="err" role="alert">{error}. If you just signed up, sign out and sign in again.</p>}
      <nav className="tabs" role="tablist">
        {TABS.filter((t) => t !== 'Activity' || isAdmin).map((t) => (
          <button key={t} role="tab" aria-selected={tab === t} onClick={() => setTab(t)}>{t}</button>
        ))}
      </nav>
      {me && tab === 'Home' && <Home go={(t) => setTab(t)} />}
      {me && tab === 'Customers' && <Agent isAdmin={isAdmin} />}
      {me && tab === 'Emails' && <Inbox />}
      {me && tab === 'Business info' && <Documents isAdmin={isAdmin} />}
      {me && tab === 'Features' && <Plugins isAdmin={isAdmin} />}
      {me && tab === 'Activity' && isAdmin && <AuditLog />}
    </main>
  );
}
