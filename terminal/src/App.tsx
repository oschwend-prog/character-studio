// The shell: demo or live backend, owner sign-in, top bar (mark + London clock), the page, the tab bar.
import type { Session } from '@supabase/supabase-js';
import { Clock3, Flame, Gauge, Library as LibraryIcon, ListChecks, Users } from 'lucide-react';
import { useEffect, useMemo, useState, type ComponentType } from 'react';
import { Mark } from './components/ui';
import { londonDate, londonTime } from './lib/format';
import { href, useNow, useRoute, type Route } from './lib/hooks';
import { StudioProvider, useStudio } from './lib/store';
import type { Backend } from './lib/types';
import { LiveBackend, hasLiveConfig, isSchemaNotExposed, supabase } from './lib/supabase';
import { Login, SetupNeeded } from './Login';
import { Budget } from './pages/Budget';
import { Channels } from './pages/Channels';
import { Library } from './pages/Library';
import { Picks } from './pages/Picks';
import { Queue } from './pages/Queue';
import { Today } from './pages/Today';

export const isDemo = () =>
  new URLSearchParams(window.location.search).get('demo') === '1' || import.meta.env.VITE_DEMO === '1';

export default function App() {
  if (isDemo()) return <Demo />;
  return <Live />;
}

function Demo() {
  const [backend, setBackend] = useState<Backend | null>(null);
  useEffect(() => {
    void import('./demo/backend').then((m) => setBackend(new m.DemoBackend()));
  }, []);
  if (!backend) return <main className="gate" aria-busy="true" />;
  return (
    <StudioProvider backend={backend}>
      <Shell
        banner={
          <div className="demo-banner" role="note">
            <strong>DEMO</strong> <span>Synthetic clips and credits · real picks</span>
            {hasLiveConfig && <a href={window.location.pathname}>Go live</a>}
          </div>
        }
        account={
          <section className="section">
            <div className="section-head">
              <h2 className="h2">Account</h2>
            </div>
            <p className="small muted" style={{ margin: 0 }}>
              Demo mode: changes stay in this tab and vanish on reload.
            </p>
          </section>
        }
      />
    </StudioProvider>
  );
}

function Live() {
  const [session, setSession] = useState<Session | null | undefined>(hasLiveConfig ? undefined : null);
  useEffect(() => {
    if (!hasLiveConfig) return;
    const sb = supabase();
    void sb.auth.getSession().then(({ data }) => setSession(data.session));
    const { data } = sb.auth.onAuthStateChange((_e, s) => setSession(s));
    return () => data.subscription.unsubscribe();
  }, []);
  const backend = useMemo(() => (session ? new LiveBackend() : null), [session?.user.id]); // eslint-disable-line react-hooks/exhaustive-deps

  if (session === undefined) return <main className="gate" aria-busy="true" />;
  if (!session || !backend) return <Login />;
  return (
    <StudioProvider backend={backend}>
      <LiveGate>
        <Shell
          account={
            <section className="section">
              <div className="section-head">
                <h2 className="h2">Account</h2>
              </div>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
                <span className="small muted">Signed in as {session.user.email}</span>
                <button type="button" className="btn ghost" onClick={() => void supabase().auth.signOut()}>
                  Sign out
                </button>
              </div>
            </section>
          }
        />
      </LiveGate>
    </StudioProvider>
  );
}

function LiveGate({ children }: { children: React.ReactNode }) {
  const { error } = useStudio();
  if (isSchemaNotExposed(error)) return <SetupNeeded />;
  return <>{children}</>;
}

const TABS: { route: Route; label: string; Icon: ComponentType<{ 'aria-hidden'?: boolean }> }[] = [
  { route: 'today', label: 'Today', Icon: Clock3 },
  { route: 'picks', label: 'Picks', Icon: Flame },
  { route: 'queue', label: 'Queue', Icon: ListChecks },
  { route: 'channels', label: 'Characters', Icon: Users },
  { route: 'library', label: 'Library', Icon: LibraryIcon },
  { route: 'budget', label: 'Budget', Icon: Gauge },
];

function Shell({ banner, account }: { banner?: React.ReactNode; account?: React.ReactNode }) {
  const { data, live, error, toasts, refresh } = useStudio();
  const { route, param } = useRoute();
  const now = useNow(10_000);
  const badge: Partial<Record<Route, { n: number; quiet?: boolean }>> = {
    queue: data?.queue.length ? { n: data.queue.length } : undefined,
    picks: data?.picks.length ? { n: data.picks.length, quiet: true } : undefined,
    today: data?.health.length ? { n: data.health.length, quiet: true } : undefined,
  };

  return (
    <div className="app">
      <a className="sr-only" href="#main">Skip to content</a>
      <header className="topbar">
        <a className="wordmark" href={href('today')} aria-label="ODD EYES, today">
          <Mark on={live} label={live ? 'Live updates connected' : 'Live updates paused'} />
          <b>ODD EYES</b>
        </a>
        <div className="where">
          <div className="clock" aria-label={`London time ${londonTime(now)}`}>{londonTime(now)}</div>
          <div className="label" style={{ fontSize: 10.5 }}>
            {londonDate(now)} · London
          </div>
        </div>
      </header>
      {banner}
      {error != null && !isSchemaNotExposed(error) && (
        <div className="demo-banner" role="alert" style={{ color: 'var(--red)' }}>
          Could not load the studio: {error instanceof Error ? error.message : String(error)}
          <button type="button" className="btn ghost" onClick={() => void refresh()}>
            Retry
          </button>
        </div>
      )}
      <main id="main">
        {route === 'today' && <Today />}
        {route === 'picks' && <Picks />}
        {route === 'queue' && <Queue focus={param} />}
        {route === 'channels' && <Channels />}
        {route === 'library' && <Library focus={param} />}
        {route === 'budget' && <Budget account={account} />}
      </main>
      <nav className="tabbar" aria-label="Sections">
        {TABS.map(({ route: r, label, Icon }) => (
          <a key={r} className="tab" href={href(r)} aria-current={route === r ? 'page' : undefined}>
            <Icon aria-hidden />
            {label}
            {badge[r] && (
              <span className={`badge${badge[r]!.quiet ? ' quiet' : ''}`} aria-label={`${badge[r]!.n} ${r === 'queue' ? 'waiting' : r === 'picks' ? 'new' : 'alerts'}`}>
                {badge[r]!.n}
              </span>
            )}
          </a>
        ))}
      </nav>
      <div className="toasts" aria-live="polite" role="status">
        {toasts.map((t) => (
          <div key={t.id} className={`toast${t.kind === 'error' ? ' error' : ''}`} role={t.kind === 'error' ? 'alert' : undefined}>
            {t.text}
          </div>
        ))}
      </div>
    </div>
  );
}
