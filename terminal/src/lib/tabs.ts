// The tab bar's order and labels. Owner 2026-10-06: "We start the channels by me uploading the clips I want generated with our
// characters; the viral search engine takes over slowly later." In the works (the drops) is first and where the app opens
// (hooks.ts HOME); the viral Picks page is "Scan", last, marked "later". Every page is as it was: only the order, that label and
// the default route changed.
import type { TabRoute } from './hooks';

export interface TabSpec {
  route: TabRoute;
  label: string;
  /** Shown with a small muted "later" mark instead of a count. */
  later?: boolean;
}

export const TABS: ReadonlyArray<TabSpec> = [
  { route: 'works', label: 'In the works' },
  { route: 'today', label: 'Today' },
  { route: 'queue', label: 'Queue' },
  { route: 'channels', label: 'Characters' },
  { route: 'library', label: 'Library' },
  { route: 'budget', label: 'Budget' },
  { route: 'picks', label: 'Scan', later: true },
];
