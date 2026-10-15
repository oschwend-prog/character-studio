// New clips (owner 2026-10-15: "share source of clips on top ... then view video on page and decide for which character and how to
// generate. after that the video moves to production stage"). The page is pre-generation only: the sources at the top (the iCloud
// clips folder, a link or a video he adds, the daily social scan), then the clips available to make, one list with a filter
// (All, Needs a character, one chip per live character), then one line for what left for production (Videos › Making). Pure
// functions over v_tracker rows; the page (pages/Clips.tsx) draws them.
import { clipChip, newestFirst } from './clipstatus';
import { clipsByCharacter } from './clipsview';
import { rankClips } from './ranking';
import type { TrackerRow } from './types';
import type { RankOrder } from './weekly';

/** Where a clip came from, said on its card. */
export type ClipSource = 'folder' | 'scan' | 'link' | 'upload';
export const SOURCE_WORDS: Record<ClipSource, string> = {
  folder: 'from your clips folder',
  scan: 'from the social scan',
  link: 'from a link you added',
  upload: 'a video you added',
};

/** The clip's source: the iCloud folder (the sync stamps `folder_hash`), the social scan (the hits job stamps `trend_stage`, or the
 * link is one of the scan's hits he used), else his link or his upload. */
export function clipSource(row: Pick<TrackerRow, 'drop_card' | 'url'>, hitUrls: ReadonlySet<string> = new Set()): ClipSource {
  const d = row.drop_card;
  if (d?.folder_hash) return 'folder';
  if (d?.trend_stage != null || hitUrls.has(row.url)) return 'scan';
  return d?.kind === 'link' ? 'link' : 'upload';
}

/** The folder row of the sources: when the newest clip came from the folder, and how many came in the last 7 days. */
export function folderStatus(rows: ReadonlyArray<TrackerRow>, now: number): { newest: string | null; week: number } {
  let newest: number | null = null;
  let week = 0;
  for (const r of rows) {
    if (!r.drop_card?.folder_hash) continue;
    const t = Date.parse(r.approved_at ?? r.drop_card.at ?? '');
    if (Number.isNaN(t)) continue;
    newest = newest == null ? t : Math.max(newest, t);
    if (now - t <= 7 * 86_400_000) week += 1;
  }
  return { newest: newest == null ? null : new Date(newest).toISOString(), week };
}

/** The list's filter: every available clip, the ones that need a character, or one character's. Kept in the address as `?c=`. */
export type AvailableFilter = 'all' | 'needs' | string;
export const parseAvailableFilter = (c: string | null, slugs: ReadonlyArray<string>): AvailableFilter =>
  c === 'needs' || (c != null && slugs.includes(c)) ? c : 'all';

export interface Available {
  /** Waiting for his choice of character: the check's pick to confirm, or still choosing (Recommend). */
  needsWho: TrackerRow[];
  /** Ready to make, best first (rankClips over the filter's clips). */
  ready: TrackerRow[];
  /** Being added or checked: on this page until they are ready. */
  checking: TrackerRow[];
  /** Blocked or failed: one closed row. */
  problems: TrackerRow[];
  /** Clips of no live character (none chosen, or a paused one): All clips shows them. */
  others: number;
  /** The filter chips' counts: what he can act on (needs a character + ready). */
  counts: Record<string, number>;
}

/** The available clips (pre-generation) under a filter. A made or making clip is never here: it moved on to production. */
export function availableClips(
  rows: ReadonlyArray<TrackerRow>,
  characters: ReadonlyArray<{ slug: string; name: string }>,
  filter: AvailableFilter,
  order: RankOrder = 'score',
): Available {
  const { groups, others, deciding } = clipsByCharacter(rows, characters, order);
  const counts: Record<string, number> = { needs: deciding.length };
  for (const g of groups) {
    counts[g.slug] = g.needsYou.length + g.ready.length;
    counts.needs += g.needsYou.length;
  }
  counts.all = counts.needs + groups.reduce((n, g) => n + g.ready.length, 0);
  const shown = filter === 'all' || filter === 'needs' ? groups : groups.filter((g) => g.slug === filter);
  const needsWho = [...(filter === 'all' || filter === 'needs' ? deciding : []), ...newestFirst(shown.flatMap((g) => g.needsYou))];
  const checking = shown.flatMap((g) => g.onTheWay).filter((r) => clipChip(r) !== 'making');
  return {
    needsWho,
    ready: filter === 'needs' ? [] : rankClips(shown.flatMap((g) => g.ready), order),
    checking: filter === 'needs' ? [] : newestFirst(checking),
    problems: filter === 'needs' ? [] : newestFirst(shown.flatMap((g) => g.problems)),
    others: others.length,
    counts,
  };
}

/** The production line under the list: what left this page (Make it sent, being made) and what waits for his OK in Videos. */
export function productionCounts(rows: ReadonlyArray<TrackerRow>): { making: number; toApprove: number } {
  let making = 0;
  let toApprove = 0;
  for (const r of rows) {
    if (!r.drop_card) continue;
    if (r.clip_state === 'awaiting_approval') toApprove += 1;
    else if (clipChip(r) === 'making') making += 1;
  }
  return { making, toApprove };
}
