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

/**
 * The five sections of terminal v2 (owner 2026-10-07), in the order of the work: Today, Clips, Videos, Characters, More.
 * `artist` (`#/artist/<slug>`, a character's page) has no tab: it is reached from the Characters page and his name.
 */
export type Route = 'today' | 'clips' | 'videos' | 'characters' | 'more' | 'artist';
/** The routes with a tab. */
export type TabRoute = Exclude<Route, 'artist'>;
export const ROUTES: Route[] = ['today', 'clips', 'videos', 'characters', 'more', 'artist'];
/** Where the app opens: Today, the daily dashboard. */
export const HOME: Route = 'today';

/** `#/videos/<clip id>`, `#/artist/franz` and `#/more/scan?c=franz`: the route, its one path parameter and the query of the hash. */
export function parseHash(hash: string): { route: Route; param: string | null; query: string } {
  const [pathPart, ...rest] = hash.replace(/^#\/?/, '').split('?');
  const [path, param] = pathPart.split('/');
  return { route: (ROUTES as string[]).includes(path) ? (path as Route) : HOME, param: param || null, query: rest.join('?') };
}

const withQuery = (hash: string, query: string) => (query ? `${hash}?${query}` : hash);
const safeDecode = (v: string) => {
  try {
    return decodeURIComponent(v);
  } catch {
    return v; // a stray % in a hand-typed address: keep it as typed
  }
};

/**
 * The new address for an old bookmark (an address of the seven-tab terminal), else null: `#/works` -> `#/clips`,
 * `#/queue[/<id>]` -> `#/videos[/<id>]`, `#/library` -> `#/characters/all` and `#/library/<id>` -> `#/characters/all?clip=<id>`,
 * `#/channels` -> `#/characters`, `#/picks?<q>` -> `#/more/scan?<q>`, `#/budget` -> `#/more/budget`, `#/today` -> `#/`.
 * A query the old address carried (`?c=franz`, `?view=list`) is kept. The new addresses, the artist page and the unknown
 * ones return null (they are not rewritten).
 */
export function upgradeHash(hash: string): string | null {
  const [pathPart, ...rest] = hash.replace(/^#\/?/, '').split('?');
  const query = rest.join('?');
  const [path, param] = pathPart.split('/');
  switch (path) {
    case 'works':
      return withQuery('#/clips', query);
    case 'queue':
      return withQuery(param ? `#/videos/${param}` : '#/videos', query);
    case 'library': {
      if (!param) return withQuery('#/characters/all', query);
      // the clip to open goes in the query (the Characters "all" view reads `clip`); whatever else the link carried stays
      const q = new URLSearchParams({ clip: safeDecode(param) });
      for (const [k, v] of new URLSearchParams(query)) if (k !== 'clip') q.append(k, v);
      return `#/characters/all?${q.toString()}`;
    }
    case 'channels':
      return withQuery('#/characters', query);
    case 'picks':
      return withQuery('#/more/scan', query);
    case 'budget':
      return withQuery('#/more/budget', query);
    case 'today':
      return withQuery('#/', query);
    default:
      return null;
  }
}

/** Rewrites an old address in place (replaceState: no history entry, no hashchange) and reads the route of the address now. */
function parse() {
  const next = upgradeHash(window.location.hash);
  if (next != null) window.history.replaceState(null, '', next);
  return parseHash(window.location.hash);
}

/**
 * Hash routing (#/videos/<clip id>): works offline in the installed app and needs no server rewrites. An old bookmark is
 * upgraded before it is parsed, at startup and on every hashchange (so a link pasted into the address bar works too).
 */
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
  return route === HOME && !param ? `#/${q}` : `#/${route}${param ? `/${param}` : ''}${q}`;
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

