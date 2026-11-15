'use client';
import { useRouter } from 'next/navigation';
import { useCallback, useEffect, useState } from 'react';
import { signOut, idToken } from '@/lib/auth';
import { api, type Connection, type Me, type Work } from '@/lib/api';
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
import PipelineBoard from '@/components/PipelineBoard';
import Automations from '@/components/Automations';
import Integrations from '@/components/Integrations';
import Impact from '@/components/Impact';
import Ask from '@/components/Ask';
import DocExtract from '@/components/DocExtract';
import { Icon } from '@/components/icons';

type Tab = 'Overview' | 'Work Queue' | 'Conversations' | 'Customers' | 'Automations' | 'Integrations' | 'Impact' | 'Ask' | 'Knowledge' | 'Settings';
type Item = { tab: Tab; icon: string; sub: string };
// Named and grouped for what the owner gets, not for how the system is built.
const NAV: { group: string; items: Item[] }[] = [
  { group: 'Today', items: [{ tab: 'Overview', icon: 'home', sub: 'What is happening in your business right now' }, { tab: 'Work Queue', icon: 'queue', sub: 'Everything that needs a person, most urgent first' }] },
  { group: 'Customers', items: [{ tab: 'Conversations', icon: 'chat', sub: 'Email, website chat and WhatsApp in one place' }, { tab: 'Customers', icon: 'users', sub: 'Your pipeline and everything known about each customer' }] },
  { group: 'Automation', items: [{ tab: 'Automations', icon: 'bolt', sub: 'What Hivemate may do by itself, and when' }, { tab: 'Integrations', icon: 'plug', sub: 'The software Hivemate works alongside' }] },
  { group: 'Insight', items: [{ tab: 'Impact', icon: 'chart', sub: 'What changed, counted from what actually happened' }, { tab: 'Ask', icon: 'spark', sub: 'Questions answered from your own records' }] },
  { group: 'Setup', items: [{ tab: 'Knowledge', icon: 'book', sub: 'What the assistant knows, and documents it has read' }, { tab: 'Settings', icon: 'cog', sub: 'Features and the activity log' }] },
];
const CONV = ['Inbox', 'Email drafts', 'Chat and website'] as const;
const hello = () => { const h = new Date().getHours(); return h < 12 ? 'Good morning' : h < 18 ? 'Good afternoon' : 'Good evening'; };

export default function Dashboard() {
  const router = useRouter();
  const [me, setMe] = useState<Me | null>(null);
  const [tab, setTab] = useState<Tab>('Overview');
  const [filter, setFilter] = useState('');
  const [conv, setConv] = useState<(typeof CONV)[number]>('Inbox');
  const [cust, setCust] = useState<'Pipeline board' | 'People'>('Pipeline board');
  const [know, setKnow] = useState<'Business documents' | 'Invoices and receipts'>('Business documents');
  const [flash, setFlash] = useState<{ connected?: string; error?: string }>({});
  const [badges, setBadges] = useState<{ work: number; urgent: number; conn: number }>({ work: 0, urgent: 0, conn: 0 });
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
  const loadBadges = useCallback(() => {
    Promise.all([api<Work>('GET', '/work'), api<Connection[]>('GET', '/connections').catch(() => [] as Connection[])])
      .then(([w, c]) => setBadges({ work: w.summary.open, urgent: w.summary.urgent, conn: c.filter((x) => x.connected && x.status !== 'connected').length })).catch(() => undefined);
  }, []);
  useEffect(() => { if (!me) return; loadBadges(); const t = setInterval(loadBadges, 30000); return () => clearInterval(t); }, [me, loadBadges, tab]);

  const isAdmin = me?.user.role === 'admin';
  const go = (t: Tab, f = '') => {
    if (t === 'Conversations' && (CONV as readonly string[]).includes(f)) { setConv(f as (typeof CONV)[number]); f = ''; }
    setFilter(f); setTab(t); window.scrollTo(0, 0);
    // On a phone the menu is one scrolling row: keep the chosen item in view.
    requestAnimationFrame(() => {
      const el = document.querySelector<HTMLElement>('.side [aria-current=page]'), side = el?.closest<HTMLElement>('.side');
      if (el && side) side.scrollTo({ left: el.offsetLeft - side.clientWidth / 2 + el.clientWidth / 2 }); // horizontal only: never moves the page
    });
  };
  const current = NAV.flatMap((g) => g.items).find((i) => i.tab === tab)!;
  const badge = (t: Tab) => (t === 'Work Queue' && badges.work ? <span className={`nbadge ${badges.urgent ? 'bad' : ''}`} aria-label={`${badges.work} open`}>{badges.work}</span>
    : t === 'Integrations' && badges.conn ? <span className="nbadge bad" aria-label={`${badges.conn} need attention`}>{badges.conn}</span> : null);
  const initials = (me?.tenant.name ?? 'H').split(' ').map((w) => w[0]).slice(0, 2).join('').toUpperCase();

  return (
    <div className="shell">
      <aside className="side">
        <div className="brand"><i className="hex"><Icon name="bolt" size={15} /></i><span>Hivemate</span></div>
        <div className="groups">
          {NAV.map((g) => (
            <div key={g.group}><h4>{g.group}</h4>
              <nav aria-label={g.group}>{g.items.map((i) => (
                <button key={i.tab} aria-current={tab === i.tab ? 'page' : undefined} onClick={() => go(i.tab)}><Icon name={i.icon} />{i.tab}{badge(i.tab)}</button>
              ))}</nav></div>
          ))}
        </div>
        <div className="who">
          <span>{me ? `${me.user.email} · ${me.user.role}` : ''}</span>
          {me?.user.platform && <a href="/platform/">Platform console</a>}
          <button onClick={() => { signOut(); router.replace('/'); }}>Sign out</button>
        </div>
      </aside>
      <main className="main"><div className="inner">
        <header className="pagehead">
          <div><h1>{tab === 'Overview' ? `${hello()}${me ? `, ${me.tenant.name}` : ''}` : tab}</h1><p className="muted">{current.sub}</p></div>
          <div className="row"><span className="muted" style={{ fontSize: 13 }}>{me?.tenant.timezone}</span><span className="avatar" title={me?.tenant.name}>{initials}</span></div>
        </header>
        {error && <p className="err" role="alert">{error}. If you just signed up, sign out and sign in again.</p>}
        {me && tab === 'Overview' && <Home go={(t, f) => go(t, f)} />}
        {me && tab === 'Work Queue' && <WorkQueue key={filter} isAdmin={isAdmin} initialType={filter} go={(t) => go(t)} />}
        {me && tab === 'Conversations' && (
          <div className="stack">
            <div className="subtabs" role="group" aria-label="Conversations">{CONV.map((s) => <button key={s} className="btn" aria-pressed={conv === s} onClick={() => setConv(s)}>{s}</button>)}</div>
            {conv === 'Inbox' && <UnifiedInbox isAdmin={isAdmin} />}
            {conv === 'Email drafts' && <div className="stack"><GmailConnect isAdmin={isAdmin} /><Inbox /></div>}
            {conv === 'Chat and website' && <Agent isAdmin={isAdmin} />}
          </div>
        )}
        {me && tab === 'Customers' && (
          <div className="stack">
            <div className="subtabs" role="group" aria-label="Customers">{(['Pipeline board', 'People'] as const).map((s) => <button key={s} className="btn" aria-pressed={cust === s} onClick={() => setCust(s)}>{s}</button>)}</div>
            {cust === 'Pipeline board' ? <PipelineBoard /> : <Customers360 />}
          </div>
        )}
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
      </div></main>
    </div>
  );
}
