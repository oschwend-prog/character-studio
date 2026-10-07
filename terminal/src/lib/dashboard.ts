// Terminal v2, Today page (owner 2026-10-07): what needs the owner now (counts) and a character's last posts. Pure functions
// over the snapshot; no browser.
import { clipChip } from './clipstatus';
import { dropCredits } from './drop';
import type { LibraryClip, Snapshot } from './types';

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
