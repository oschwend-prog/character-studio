// Totals for all videos (owner 2026-10-15): on Characters → "All videos" a strip of totals for the current filter (character /
// platform), and on a character's page his Reels' views over all time. From v_library: every clip carries its posts, each post its
// LATEST metric snapshot (views, likes, comments, shares, saves; a figure the platform did not give is null). Only posts with status
// "posted" count. A figure a post has not got is left out of its sum and never counted as 0; every sum says how many posts it covers.
// Pure functions, no browser.
import { platformName } from './format';
import type { LibraryClip, Platform } from './types';

/** The most clips the terminal loads into the library (supabase.ts asks v_library for this many, newest first). */
export const LIBRARY_LOAD_LIMIT = 300;

export const TOTAL_METRICS = ['views', 'likes', 'comments', 'shares', 'saves'] as const;
export type TotalMetric = (typeof TOTAL_METRICS)[number];

/** One sum: `sum` is null when no post has the figure; `covers` is how many posts have it. */
export interface MetricTotal {
  sum: number | null;
  covers: number;
}

export interface PostedTotals {
  /** Clips with at least one counted post (a video posted on two platforms is one). */
  videos: number;
  /** The counted posts: status posted, on the platform asked for. */
  posts: number;
  metrics: Record<TotalMetric, MetricTotal>;
}

export interface TotalsFilter {
  /** A character slug, or 'all' / absent for everyone. */
  character?: string;
  /** 'tiktok' or 'instagram', or 'all' / absent for both. The filter is on the post, not the clip. */
  platform?: Platform | 'all';
}

/** A plain count from a number or numeric string; anything else (null, NaN, negative, text) is "no figure". */
function figure(v: unknown): number | null {
  const x = typeof v === 'string' && v.trim() !== '' ? Number(v) : v;
  return typeof x === 'number' && Number.isFinite(x) && x >= 0 ? x : null;
}

/**
 * The posted videos of `clips` for the filter and the sum of their posts' latest figures. A post with no figure for a metric adds
 * nothing to it and is not in its `covers`; a metric no post has is `{ sum: null, covers: 0 }`, not 0.
 */
export function postedTotals(clips: ReadonlyArray<LibraryClip>, filter: TotalsFilter = {}): PostedTotals {
  const character = filter.character && filter.character !== 'all' ? filter.character : null;
  const platform = filter.platform && filter.platform !== 'all' ? filter.platform : null;
  const sums = Object.fromEntries(TOTAL_METRICS.map((m) => [m, { sum: null, covers: 0 }])) as Record<TotalMetric, MetricTotal>;
  let videos = 0;
  let posts = 0;
  for (const clip of clips) {
    if (character && clip.character_slug !== character) continue;
    const counted = (clip.posts ?? []).filter((p) => p.status === 'posted' && (!platform || p.platform === platform));
    if (counted.length === 0) continue;
    videos += 1;
    posts += counted.length;
    for (const p of counted) {
      for (const m of TOTAL_METRICS) {
        const v = figure(p[m]);
        if (v == null) continue;
        sums[m] = { sum: (sums[m].sum ?? 0) + v, covers: sums[m].covers + 1 };
      }
    }
  }
  return { videos, posts, metrics: sums };
}

/** The filter in words: "All characters, any platform", "Franz, TikTok". `nameOf` gives a character's name from his slug. */
export function scopeLine(character: string, platform: Platform | 'all', nameOf: (slug: string) => string): string {
  return `${character === 'all' ? 'All characters' : nameOf(character)}, ${platform === 'all' ? 'any platform' : platformName(platform)}`;
}
