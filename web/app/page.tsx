'use client';
import { useRouter } from 'next/navigation';
import { useEffect, useState, type FormEvent } from 'react';
import { confirm, idToken, signIn, signUp } from '@/lib/auth';

type Mode = 'signin' | 'signup' | 'confirm';

export default function Home() {
  const router = useRouter();
  const [mode, setMode] = useState<Mode>('signin');
  const [email, setEmail] = useState(''); const [password, setPassword] = useState('');
  const [business, setBusiness] = useState(''); const [code, setCode] = useState('');
  const [error, setError] = useState(''); const [busy, setBusy] = useState(false);

  useEffect(() => { idToken().then((t) => t && router.replace('/dashboard')); }, [router]);

  async function submit(e: FormEvent) {
    e.preventDefault(); setError(''); setBusy(true);
    try {
      if (mode === 'signup') { await signUp(email, password, business); setMode('confirm'); }
      else if (mode === 'confirm') { await confirm(email, code); await signIn(email, password); router.replace('/dashboard'); }
      else { await signIn(email, password); router.replace('/dashboard'); }
    } catch (err) { setError((err as Error).message); } finally { setBusy(false); }
  }

  return (
    <main className="wrap"><div className="auth card stack">
      <div><h1>Hivemate</h1><p className="muted">AI automation for New Zealand small businesses</p></div>
      <form className="stack" onSubmit={submit}>
        {mode !== 'confirm' && <>
          {mode === 'signup' && <label>Business name<input required maxLength={100} value={business} onChange={(e) => setBusiness(e.target.value)} /></label>}
          <label>Email<input type="email" required autoComplete="email" value={email} onChange={(e) => setEmail(e.target.value)} /></label>
          <label>Password<input type="password" required minLength={12} autoComplete={mode === 'signup' ? 'new-password' : 'current-password'} value={password} onChange={(e) => setPassword(e.target.value)} />
            {mode === 'signup' && <span>12+ characters with a number and a symbol</span>}</label>
        </>}
        {mode === 'confirm' && <label>Code sent to {email}<input required inputMode="numeric" value={code} onChange={(e) => setCode(e.target.value)} /></label>}
        {error && <p className="err" role="alert">{error}</p>}
        <button className="btn primary" disabled={busy}>{mode === 'signin' ? 'Sign in' : mode === 'signup' ? 'Create account' : 'Confirm and sign in'}</button>
      </form>
      {mode !== 'confirm' && <button className="btn" onClick={() => { setError(''); setMode(mode === 'signin' ? 'signup' : 'signin'); }}>
        {mode === 'signin' ? 'New business? Create an account' : 'Have an account? Sign in'}</button>}
    </div></main>
  );
}
