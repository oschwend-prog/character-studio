// The tab bar's order and labels. Terminal v2 (owner 2026-10-07): five sections in the order of the work, Today first (the
// home, hooks.ts HOME): Today, Clips (the owner's clip folder), Videos (everything after Make it), Characters, More (the viral
// scan, budget, health and settings). Old addresses keep working (hooks.ts upgradeHash). The viral scan's small muted "later"
// mark is on the Scan page inside More, not on a tab.
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
