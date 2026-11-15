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
import GmailConnect from '@/components/GmailConnect';
import WorkQueue from '@/components/WorkQueue';
import UnifiedInbox from '@/components/UnifiedInbox';
import Customers360 from '@/components/Customers360';
import Automations from '@/components/Automations';
import Integrations from '@/components/Integrations';
import Impact from '@/components/Impact';
import Ask from '@/components/Ask';
import DocExtract from '@/components/DocExtract';

// Named for what the owner gets, not for how the system is built.
const TABS = ['Overview', 'Work Queue', 'Conversations', 'Customers', 'Automations', 'Integrations', 'Impact', 'Ask', 'Knowledge', 'Settings'] as const;
type Tab = (typeof TABS)[number];
type Go = 'Work Queue' | 'Conversations' | 'Knowledge' | 'Settings' | 'Impact' | 'Integrations' | 'Automations' | 'Customers';

export default function Dashboard() {
  const router = useRouter();
  const [me, setMe] = useState<Me | null>(null);
  const [tab, setTab] = useState<Tab>('Overview');
  const [filter, setFilter] = useState('');
  const [conv, setConv] = useState<'Inbox' | 'Email drafts' | 'Chat and website'>('Inbox');
  const [know, setKnow] = useState<'Business documents' | 'Invoices and receipts'>('Business documents');
  const [flash, setFlash] = useState<{ connected?: string; error?: string }>({});
  const [error, setError] = useState('');

  useEffect(() => {
    idToken().then((t) => {
      if (!t) return router.replace('/');
      api<Me>('GET', '/me').then(setMe).catch((e: Error) => setError(e.message));
    });
  }, [router]);
  useEffect(() => { // returning from Microsoft / Xero sign-in
    const q = new URLSearchParams(window.location.search);
    if (q.get('connected') || q.get('connect_error')) { setFlash({ connected: q.get('connected') ?? undefined, error: q.get('connect_error') ?? undefined }); setTab('Integrations'); window.history.replaceState(null, '', window.location.pathname); }
  }, []);

  const isAdmin = me?.user.role === 'admin';
  const go = (t: Go, f = '') => { setFilter(f); setTab(t); };
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
        {TABS.map((t) => <button key={t} role="tab" aria-selected={tab === t} onClick={() => go(t as Go)}>{t}</button>)}
      </nav>
      {me && tab === 'Overview' && <Home go={(t, f) => go(t, f)} />}
      {me && tab === 'Work Queue' && <WorkQueue key={filter} isAdmin={isAdmin} initialType={filter} go={(t) => go(t)} />}
      {me && tab === 'Conversations' && (
        <div className="stack">
          <div className="subtabs" role="group" aria-label="Conversations">{(['Inbox', 'Email drafts', 'Chat and website'] as const).map((s) => <button key={s} className="btn" aria-pressed={conv === s} onClick={() => setConv(s)}>{s}</button>)}</div>
          {conv === 'Inbox' && <UnifiedInbox isAdmin={isAdmin} />}
          {conv === 'Email drafts' && <div className="stack"><GmailConnect isAdmin={isAdmin} /><Inbox /></div>}
          {conv === 'Chat and website' && <Agent isAdmin={isAdmin} />}
        </div>
      )}
      {me && tab === 'Customers' && <Customers360 />}
      {me && tab === 'Automations' && <Automations isAdmin={isAdmin} />}
      {me && tab === 'Integrations' && <Integrations isAdmin={isAdmin} flash={flash} />}
      {me && tab === 'Impact' && <Impact go={(t) => go(t)} />}
      {me && tab === 'Ask' && <Ask />}
      {me && tab === 'Knowledge' && (
        <div className="stack">
          <div className="subtabs" role="group" aria-label="Knowledge">{(['Business documents', 'Invoices and receipts'] as const).map((s) => <button key={s} className="btn" aria-pressed={know === s} onClick={() => setKnow(s)}>{s}</button>)}</div>
          {know === 'Business documents' ? <Documents isAdmin={isAdmin} /> : <DocExtract />}
        </div>
      )}
      {me && tab === 'Settings' && <div className="stack"><Plugins isAdmin={isAdmin} />{isAdmin && <><h2>Activity log</h2><AuditLog /></>}</div>}
    </main>
  );
}
