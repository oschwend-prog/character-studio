// Owner sign-in: a magic link to the owner's email. RLS only lets the owner's email see anything, so
// another address signs in to an empty terminal; the page does not reveal which address that is.
import { useState, type FormEvent } from 'react';
import { Mark, Spinner } from './components/ui';
import { supabase, hasLiveConfig } from './lib/supabase';

export function Login() {
  const [email, setEmail] = useState('');
  const [state, setState] = useState<'idle' | 'sending' | 'sent' | 'error'>('idle');
  const [error, setError] = useState<string | null>(null);

  const submit = async (e: FormEvent) => {
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
        ) : state === 'sent' ? (
          <div className="stack" style={{ gap: 10 }} role="status">
            <p style={{ margin: 0 }}>Check your inbox: the sign-in link is on its way to {email}.</p>
            <p className="small muted" style={{ margin: 0 }}>
              Open it on this device. On the installed app, open the link in the browser once; the app picks the session up.
            </p>
            <button type="button" className="btn ghost" onClick={() => setState('idle')}>
              Use another address
            </button>
          </div>
        ) : (
          <form className="stack" style={{ gap: 12 }} onSubmit={submit}>
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
              {state === 'sending' && <Spinner />} Email me a sign-in link
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
