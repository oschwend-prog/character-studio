// The tab bar's order and labels, and the views inside Characters and More. Terminal v2 (owner 2026-10-07): five sections in the
// order of the work, Today first (the home, hooks.ts HOME): Today, Clips (the owner's clip folder), Videos (everything after Make
// it), Characters, More (the viral scan, budget, health and settings). Old addresses keep working (hooks.ts upgradeHash). The
// viral scan's small muted "later" mark is on the Scan view inside More, not on a tab.
import type { TabRoute } from './hooks';

export interface TabSpec {
  route: TabRoute;
  label: string;
}

export const TABS: ReadonlyArray<TabSpec> = [
  { route: 'today', label: 'Today' },
  { route: 'clips', label: 'Clips' },
  { route: 'videos', label: 'Videos' },
  { route: 'characters', label: 'Characters' },
  { route: 'more', label: 'More' },
];

/** More's three views (`#/more/<view>`): the viral scan (it keeps running, aside), the budget, and health. */
export const MORE_VIEWS = [
  { id: 'scan', label: 'Scan' },
  { id: 'budget', label: 'Budget' },
  { id: 'health', label: 'Health' },
] as const;
export type MoreView = (typeof MORE_VIEWS)[number]['id'];

/** The view of `#/more/<param>`; no parameter or an unknown one is the Scan (the old `#/picks`). */
export const moreView = (param: string | null | undefined): MoreView => MORE_VIEWS.find((v) => v.id === param)?.id ?? 'scan';

/** Characters' two views: the character cards (`#/characters`) and every video (`#/characters/all`, the old Library). */
export const CHARACTERS_VIEWS = [
  { id: 'cards', label: 'Characters' },
  { id: 'all', label: 'All videos' },
] as const;
export type CharactersView = (typeof CHARACTERS_VIEWS)[number]['id'];

/** The view of `#/characters/<param>`: `all` is every video, anything else the cards. */
export const charactersView = (param: string | null | undefined): CharactersView => (param === 'all' ? 'all' : 'cards');
