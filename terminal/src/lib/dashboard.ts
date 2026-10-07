// Terminal v2, Today page (owner 2026-10-07): what needs the owner now (counts) and a character's last posts. Pure functions
// over the snapshot; no browser.
import { clipChip, filterClips } from './clipstatus';
import { dropCredits } from './drop';
import { formatViews } from './format';
import { orderRoster } from './roster';
import type { Budget, LibraryClip, Snapshot } from './types';

export interface TodayCounts {
  /** Ready clips whose character the studio chose: the owner confirms or changes it. */
  needCharacter: number;
  /** Ready clips with the owner's character: Make it. */
  ready: number;
  /** What making every ready clip costs, each with its own Adjust (the price the drops table shows). */
  readyCredits: number;
  making: number;
  /** Finished videos waiting for the owner's OK (the Queue). */
  toApprove: number;
}

/** The Today page's counters: the chips of the dropped clips (rows with a drop card) and the length of the approval queue. */
export function todayCounts(data: Snapshot): TodayCounts {
  const counts: TodayCounts = { needCharacter: 0, ready: 0, readyCredits: 0, making: 0, toApprove: data.queue.length };
  for (const r of data.tracker) {
    const d = r.drop_card;
    if (!d) continue;
    switch (clipChip(r)) {
      case 'pick':
        counts.needCharacter += 1;
        break;
      case 'ready':
        counts.ready += 1;
        counts.readyCredits += dropCredits(d, d.adjust ?? {});
        break;
      case 'making':
        counts.making += 1;
        break;
    }
  }
  return counts;
}

export interface LastPost {
  clipId: string;
  hook: string | null;
  postedAt: string | null;
  /** Summed over the clip's posts; null while no post has that number yet ("no numbers yet" is not 0). */
  views: number | null;
  likes: number | null;
  shares: number | null;
}

/** The sum of the numbers read so far, or null when no post has one yet. */
const sum = (xs: ReadonlyArray<number | null>): number | null => {
  const read = xs.filter((x): x is number => x != null);
  return read.length ? read.reduce((total, x) => total + x, 0) : null;
};

/**
 * A character's last `n` posted clips, newest first, with views, likes and shares summed over the clip's posts. A number no post
 * has yet (no metrics snapshot) is null, so a just-posted clip reads "no numbers yet" instead of 0.
 */
export function lastPosts(library: ReadonlyArray<LibraryClip>, slug: string, n = 3): LastPost[] {
  const at = (c: LibraryClip) => Date.parse(c.posted_at ?? c.created_at) || 0;
  return library
    .filter((c) => c.character_slug === slug && c.state === 'posted')
    .sort((a, b) => at(b) - at(a) || a.id.localeCompare(b.id))
    .slice(0, n)
    .map((c) => ({
      clipId: c.id,
      hook: c.hook,
      postedAt: c.posted_at,
      views: sum(c.posts.map((p) => p.views)),
      likes: sum(c.posts.map((p) => p.likes)),
      shares: sum(c.posts.map((p) => p.shares)),
    }));
}

/** The numbers of one last post on one line; a number no post has yet is a dash, and none at all reads "no numbers yet" (never 0). */
export function postNumbers(p: Pick<LastPost, 'views' | 'likes' | 'shares'>): string {
  if (p.views == null && p.likes == null && p.shares == null) return 'no numbers yet';
  return `${formatViews(p.views)} views · ${formatViews(p.likes)} likes · ${formatViews(p.shares)} shares`;
}

export interface CharacterPosts {
  slug: string;
  name: string;
  posts: LastPost[];
}

/** Every live character in the owner's order with his last `n` posts (none yet is an empty list); a character not live is left out. */
export function liveLastPosts(data: Pick<Snapshot, 'characters' | 'library'>, n = 3): CharacterPosts[] {
  return orderRoster(data.characters.filter((c) => c.status === 'live')).map((c) => ({
    slug: c.slug,
    name: c.name,
    posts: lastPosts(data.library, c.slug, n),
  }));
}

/** What is left of this month's cap (never below 0); null while the budget has not loaded. */
export function creditsLeft(b: Pick<Budget, 'cap' | 'committed'> | null | undefined): number | null {
  return b ? Math.max(0, b.cap - b.committed) : null;
}

/** Tonight is per live character: the channels of a designing, paused or retired character stay off the board. */
export function liveChannels<T extends { character_status: string }>(channels: ReadonlyArray<T>): T[] {
  return channels.filter((c) => c.character_status === 'live');
}

/** Dropped clips the owner has to look at: blocked (can't be used) or failed. v_health has no drops, so Today counts them here. */
export const problemClips = (data: Pick<Snapshot, 'tracker'>): number => filterClips(data.tracker, 'problems').length;

/** The warning row for those clips; it links to the Clips page's Blocked or failed filter. */
export const problemClipsLine = (n: number): string => (n === 1 ? '1 clip is blocked or failed' : `${n} clips are blocked or failed`);

/** The Today tab's badge: every warning Today lists, the v_health rows plus the blocked or failed clips (so it matches the page). */
export const warningCount = (data: Pick<Snapshot, 'health' | 'tracker'>): number => data.health.length + problemClips(data);

/** Whether Today shows its warnings: something in v_health (a failed post, the daily run, low credits) or a blocked or failed drop. */
export const hasWarnings = (data: Pick<Snapshot, 'health' | 'tracker'>): boolean => warningCount(data) > 0;
