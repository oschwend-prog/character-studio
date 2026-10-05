import { useEffect, useState } from 'react';

/** The current time, re-rendered every `ms` (the London clock, countdowns). */
export function useNow(ms = 15_000): number {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const id = window.setInterval(() => setNow(Date.now()), ms);
    return () => window.clearInterval(id);
  }, [ms]);
  return now;
}

export type Route = 'today' | 'picks' | 'queue' | 'channels' | 'library' | 'budget';
export const ROUTES: Route[] = ['today', 'picks', 'queue', 'channels', 'library', 'budget'];

const parse = (): { route: Route; param: string | null } => {
  const [path, param] = window.location.hash.replace(/^#\/?/, '').split('/');
  return { route: (ROUTES as string[]).includes(path) ? (path as Route) : 'today', param: param ?? null };
};

/** Hash routing (#/queue/<clip id>): works offline in the installed app and needs no server rewrites. */
export function useRoute() {
  const [r, setR] = useState(parse);
  useEffect(() => {
    const on = () => {
      setR(parse());
      window.scrollTo({ top: 0 });
    };
    window.addEventListener('hashchange', on);
    return () => window.removeEventListener('hashchange', on);
  }, []);
  return r;
}

export const href = (route: Route, param?: string) =>
  route === 'today' ? '#/' : `#/${route}${param ? `/${param}` : ''}`;
