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
  views: number;
  likes: number;
  shares: number;
}

const sum = (xs: ReadonlyArray<number | null>) => xs.reduce<number>((total, x) => total + (x ?? 0), 0);

/** A character's last `n` posted clips, newest first, with views, likes and shares summed over the clip's posts (a metric not read yet counts 0). */
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
