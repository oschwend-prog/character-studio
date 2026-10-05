import { useCallback, useEffect, useState } from 'react';
import { loadCharacterFilter, saveCharacterFilter } from './rules';

/** The current time, re-rendered every `ms` (the London clock, countdowns). */
export function useNow(ms = 15_000): number {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const id = window.setInterval(() => setNow(Date.now()), ms);
    return () => window.clearInterval(id);
  }, [ms]);
  return now;
}

export type Route = 'today' | 'picks' | 'works' | 'queue' | 'channels' | 'library' | 'budget';
export const ROUTES: Route[] = ['today', 'picks', 'works', 'queue', 'channels', 'library', 'budget'];

/** `#/queue/<clip id>` and `#/picks?c=biscuit`: the route, its one path parameter and the query of the hash. */
export function parseHash(hash: string): { route: Route; param: string | null; query: string } {
  const [pathPart, ...rest] = hash.replace(/^#\/?/, '').split('?');
  const [path, param] = pathPart.split('/');
  return { route: (ROUTES as string[]).includes(path) ? (path as Route) : 'today', param: param || null, query: rest.join('?') };
}

const parse = () => parseHash(window.location.hash);

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

export const href = (route: Route, param?: string, query?: Record<string, string>) => {
  const q = query && Object.keys(query).length ? `?${new URLSearchParams(query).toString()}` : '';
  return route === 'today' ? `#/${q}` : `#/${route}${param ? `/${param}` : ''}${q}`;
};

const safeStorage = (): Storage | null => {
  try {
    return window.localStorage;
  } catch {
    return null; // some browsers throw on the accessor itself (blocked site data)
  }
};

/**
 * The character switcher's state, shared by Picks, Queue and Library: `?c=<slug>` in the page URL or the hash (a deep
 * link) wins, else the viewer's last choice from localStorage, else `all`. Every read and write is guarded: a private
 * window or blocked site data leaves the page working, it just forgets the choice.
 */
export function useCharacterFilter(known: ReadonlyArray<string>): [string, (v: string) => void] {
  const { query } = useRoute();
  const key = known.join(',');
  const read = useCallback(
    () => loadCharacterFilter(safeStorage(), query || window.location.search, known),
    [query, key], // eslint-disable-line react-hooks/exhaustive-deps
  );
  const [value, setValue] = useState(read);
  useEffect(() => {
    const v = read();
    setValue(v);
    // a deep link is an explicit choice: it is remembered like a tap on the switcher
    if (new URLSearchParams(query || window.location.search).get('c') === v) saveCharacterFilter(safeStorage(), v);
  }, [read]); // eslint-disable-line react-hooks/exhaustive-deps
  const choose = useCallback((v: string) => {
    setValue(v);
    saveCharacterFilter(safeStorage(), v);
  }, []);
  return [value, choose];
}

