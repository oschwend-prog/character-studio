// Owner sign-in: one email carrying a magic link and a 6-digit code (the Supabase email template must
// include {{ .Token }}). In the installed app the code is the primary route. RLS only lets the owner's
// email see anything, so another address signs in to an empty terminal; the page does not say which.
import { useState, type FormEvent } from 'react';
import { Mark, Spinner } from './components/ui';
import { isStandalone, normaliseOtpCode } from './lib/auth';
import { supabase, hasLiveConfig } from './lib/supabase';

export function Login() {
  const standalone = isStandalone();
  const [email, setEmail] = useState('');
  const [code, setCode] = useState('');
  const [state, setState] = useState<'idle' | 'sending' | 'sent' | 'verifying' | 'error'>('idle');
  const [error, setError] = useState<string | null>(null);

  const send = async (e: FormEvent) => {
    e.preventDefault();
    setState('sending');
    setError(null);
    const { error } = await supabase().auth.signInWithOtp({
      email: email.trim(),
      options: { emailRedirectTo: `${window.location.origin}${window.location.pathname}` },
    });
    if (error) {
      setState('error');
      setError(error.message);
    } else {
      setState('sent');
    }
  };

  // The 6-digit code works everywhere; in the installed app it is the only route that works, because a
  // link from Mail opens Safari, whose storage is not the app's (the PKCE verifier stays behind).
  const verify = async (e: FormEvent) => {
    e.preventDefault();
    const token = normaliseOtpCode(code);
    if (!token) {
      setError('Enter the 6-digit code from the email.');
      return;
    }
    setState('verifying');
    setError(null);
    const { error } = await supabase().auth.verifyOtp({ email: email.trim(), token, type: 'email' });
    if (error) {
      setState('sent');
      setError(error.message);
    }
  };

  const sent = state === 'sent' || state === 'verifying';
  return (
    <main className="gate">
      <div className="gate-box">
        <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
          <Mark />
          <span className="wordmark">
            <b>ODD EYES</b>
          </span>
        </div>
        <h1 className="h1">The studio terminal</h1>
        {!hasLiveConfig ? (
          <p className="muted">
            This build has no Supabase settings (<code>VITE_SUPABASE_URL</code>, <code>VITE_SUPABASE_ANON_KEY</code>). Open the{' '}
            <a href="?demo=1">demo</a> instead.
          </p>
        ) : sent ? (
          <form className="stack" style={{ gap: 12 }} onSubmit={verify}>
            <p style={{ margin: 0 }} role="status">
              {standalone
                ? `Enter the code we emailed to ${email}.`
                : `Check ${email}: tap the link in the email, or enter its code here.`}
            </p>
            <div className="field">
              <label className="label" htmlFor="otp">Code from the email</label>
              <input
                id="otp"
                className="input num"
                inputMode="numeric"
                autoComplete="one-time-code"
                maxLength={12}
                value={code}
                onChange={(e) => setCode(e.target.value)}
                aria-invalid={error ? true : undefined}
                aria-describedby={error ? 'login-err' : 'otp-hint'}
                autoFocus={standalone}
              />
              <span className="hint" id="otp-hint">
                {standalone ? 'The link in the email opens Safari, not this app: use the code here.' : 'The link works in this browser; the code works anywhere.'}
              </span>
            </div>
            <button type="submit" className={`btn ${standalone ? 'primary' : 'line'} block`} disabled={state === 'verifying' || !code.trim()} aria-busy={state === 'verifying'}>
              {state === 'verifying' && <Spinner />} Sign in with the code
            </button>
            {error && (
              <span id="login-err" className="error-text" role="alert">
                {error}
              </span>
            )}
            <button type="button" className="btn ghost" onClick={() => { setState('idle'); setCode(''); setError(null); }}>
              Use another address
            </button>
          </form>
        ) : (
          <form className="stack" style={{ gap: 12 }} onSubmit={send}>
            <div className="field">
              <label className="label" htmlFor="email">Owner email</label>
              <input
                id="email"
                className="input"
                type="email"
                autoComplete="email"
                inputMode="email"
                required
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                aria-invalid={state === 'error' || undefined}
                aria-describedby={error ? 'login-err' : undefined}
              />
            </div>
            <button type="submit" className="btn primary block" disabled={state === 'sending' || !email.trim()} aria-busy={state === 'sending'}>
              {state === 'sending' && <Spinner />} {standalone ? 'Email me a sign-in code' : 'Email me a sign-in link'}
            </button>
            {error && (
              <span id="login-err" className="error-text" role="alert">
                {error}
              </span>
            )}
            <a className="link" href="?demo=1">
              Look around the demo first
            </a>
          </form>
        )}
      </div>
    </main>
  );
}

/** Schema `studio` is not exposed to the API yet: say exactly what to click. */
export function SetupNeeded() {
  return (
    <main className="gate">
      <div className="gate-box">
        <Mark on={false} label="ODD EYES, not connected" />
        <h1 className="h1">One switch left in Supabase</h1>
        <p className="muted" style={{ margin: 0 }}>
          You are signed in, but the API does not serve the <code>studio</code> schema yet.
        </p>
        <ol className="steps">
          <li>
            Supabase dashboard → project <code>hkcafvzjwkeibbmvskko</code> → Settings → API (Data API).
          </li>
          <li>
            Exposed schemas: add <code>studio</code>, save.
          </li>
          <li>Come back and pull to refresh.</li>
        </ol>
        <a className="btn line" href="?demo=1">
          Open the demo meanwhile
        </a>
      </div>
    </main>
  );
}
