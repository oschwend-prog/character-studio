// One snapshot of the studio for every screen, refreshed on Realtime events (clips, posts, favorites),
// on focus and once a minute. Actions go through `run`, which shows the outcome and reloads.
import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState, type ReactNode } from 'react';
import type { Backend, Snapshot } from './types';

export interface Toast {
  id: number;
  text: string;
  kind: 'ok' | 'error';
}

interface StudioCtx {
  backend: Backend;
  data: Snapshot | null;
  error: unknown;
  live: boolean;
  busy: ReadonlySet<string>;
  toasts: Toast[];
  refresh(): Promise<void>;
  /** Run an owner action under `key` (disables its controls), toast the result, reload. */
  run(key: string, action: () => Promise<unknown>, done?: string): Promise<boolean>;
  toast(text: string, kind?: Toast['kind']): void;
}

const Ctx = createContext<StudioCtx | null>(null);

export function useStudio(): StudioCtx {
  const v = useContext(Ctx);
  if (!v) throw new Error('useStudio outside StudioProvider');
  return v;
}

const message = (e: unknown) => (e instanceof Error ? e.message : String(e));

export function StudioProvider({ backend, children }: { backend: Backend; children: ReactNode }) {
  const [data, setData] = useState<Snapshot | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [live, setLive] = useState(false);
  const [busy, setBusy] = useState<ReadonlySet<string>>(new Set());
  const [toasts, setToasts] = useState<Toast[]>([]);
  const loading = useRef<Promise<void> | null>(null);
  const again = useRef(false);

  const refresh = useCallback(async () => {
    if (loading.current) {
      again.current = true;
      return loading.current;
    }
    const p = (async () => {
      try {
        do {
          again.current = false;
          setData(await backend.load());
          setError(null);
        } while (again.current);
      } catch (e) {
        setError(e);
      } finally {
        loading.current = null;
      }
    })();
    loading.current = p;
    return p;
  }, [backend]);

  const toast = useCallback((text: string, kind: Toast['kind'] = 'ok') => {
    const id = Date.now() + Math.random();
    setToasts((t) => [...t.slice(-2), { id, text, kind }]);
    window.setTimeout(() => setToasts((t) => t.filter((x) => x.id !== id)), kind === 'error' ? 7000 : 3200);
  }, []);

  const run = useCallback(
    async (key: string, action: () => Promise<unknown>, done?: string) => {
      setBusy((b) => new Set(b).add(key));
      try {
        await action();
        if (done) toast(done);
        return true;
      } catch (e) {
        toast(message(e), 'error');
        return false;
      } finally {
        setBusy((b) => {
          const n = new Set(b);
          n.delete(key);
          return n;
        });
        void refresh();
      }
    },
    [refresh, toast],
  );

  useEffect(() => {
    void refresh();
    let timer: number | undefined;
    const unsubscribe = backend.subscribe(
      () => {
        window.clearTimeout(timer);
        timer = window.setTimeout(() => void refresh(), 250);
      },
      setLive,
    );
    const minute = window.setInterval(() => void refresh(), 60_000);
    const onVisible = () => document.visibilityState === 'visible' && void refresh();
    document.addEventListener('visibilitychange', onVisible);
    return () => {
      unsubscribe();
      window.clearTimeout(timer);
      window.clearInterval(minute);
      document.removeEventListener('visibilitychange', onVisible);
    };
  }, [backend, refresh]);

  const value = useMemo(
    () => ({ backend, data, error, live, busy, toasts, refresh, run, toast }),
    [backend, data, error, live, busy, toasts, refresh, run, toast],
  );
  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}
