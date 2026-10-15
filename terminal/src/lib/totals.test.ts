// Totals for all videos (owner 2026-10-15): the posted videos for a filter (character / platform) with the sum of their latest views,
// likes, comments, shares and saves. A figure a post has not got is left out of its sum, never counted as 0, and every sum says how
// many of the posts it covers.
import { describe, expect, it } from 'vitest';
import { postedTotals, scopeLine } from './totals';
import type { LibraryClip, LibraryPost } from './types';

const post = (over: Partial<LibraryPost> = {}): LibraryPost => ({
  post_id: Math.random().toString(36).slice(2), platform: 'instagram', handle: '@franz.ig', status: 'posted',
  scheduled_for: '2026-10-14T18:00:00Z', url: null, views: null, likes: null, comments: null, shares: null, saves: null, captured_at: null,
  ...over,
});

const clip = (id: string, character_slug: string, posts: LibraryPost[]): LibraryClip => ({
  id, character_slug, character_name: character_slug, mode: 'dropin', state: 'posted', hook: null, caption: null, master_path: null,
  reject_reason: null, created_at: '2026-10-14T10:00:00Z', cost_credits: null, outlier_x: null, format_id: null, posts,
  platforms: [...new Set(posts.map((p) => p.platform))], views: null, posted_at: null,
});

const library: LibraryClip[] = [
  clip('a', 'franz', [
    post({ platform: 'instagram', views: 1000, likes: 100, comments: 10, shares: 5, saves: 20 }),
    post({ platform: 'tiktok', handle: '@franz.tt', views: 4000, likes: 300, comments: null, shares: 7, saves: null }),
  ]),
  clip('b', 'franz', [post({ platform: 'instagram', views: 500, likes: null, comments: 2, shares: null, saves: 1 })]),
  clip('c', 'lenny', [post({ platform: 'instagram', views: null }), post({ platform: 'tiktok', views: 250, likes: 0 })]), // never measured / a real 0
  clip('d', 'franz', [post({ status: 'scheduled', views: 99999 }), post({ status: 'failed', views: 88888 })]), // not posted: out
  clip('e', 'franz', []),
];

describe('postedTotals', () => {
  it('counts the posted videos and posts and adds up the latest figures, with how many posts each sum covers', () => {
    const t = postedTotals(library);
    expect(t.videos).toBe(3); // a, b, c: d has no posted post, e has no post at all
    expect(t.posts).toBe(5);
    expect(t.metrics.views).toEqual({ sum: 1000 + 4000 + 500 + 250, covers: 4 }); // one post was never measured
    expect(t.metrics.likes).toEqual({ sum: 100 + 300 + 0, covers: 3 }); // a real 0 counts as a post covered
    expect(t.metrics.comments).toEqual({ sum: 10 + 2, covers: 2 });
    expect(t.metrics.shares).toEqual({ sum: 5 + 7, covers: 2 });
    expect(t.metrics.saves).toEqual({ sum: 20 + 1, covers: 2 });
  });

  it('leaves a missing figure out of the sum and never counts it as 0', () => {
    const t = postedTotals([clip('x', 'franz', [post({ views: 10, likes: null }), post({ views: 20, likes: null })])]);
    expect(t.metrics.views).toEqual({ sum: 30, covers: 2 });
    expect(t.metrics.likes).toEqual({ sum: null, covers: 0 }); // nothing known: null, not 0
  });

  it('ignores a figure that is not a plain count (negative, NaN, text) and reads a numeric string', () => {
    const odd = post({ views: -5, likes: Number.NaN, comments: '12' as unknown as number, shares: 'many' as unknown as number });
    const t = postedTotals([clip('x', 'franz', [odd])]);
    expect(t.metrics.views.sum).toBeNull();
    expect(t.metrics.likes.sum).toBeNull();
    expect(t.metrics.comments).toEqual({ sum: 12, covers: 1 });
    expect(t.metrics.shares.sum).toBeNull();
  });

  it('filters by character', () => {
    const t = postedTotals(library, { character: 'lenny' });
    expect(t.videos).toBe(1);
    expect(t.posts).toBe(2);
    expect(t.metrics.views).toEqual({ sum: 250, covers: 1 });
  });

  it('filters by platform at the post, so a video posted on both counts only its post on that platform', () => {
    const t = postedTotals(library, { platform: 'tiktok' });
    expect(t.videos).toBe(2); // a and c each have a TikTok post
    expect(t.posts).toBe(2);
    expect(t.metrics.views).toEqual({ sum: 4250, covers: 2 });
    expect(postedTotals(library, { platform: 'instagram' }).metrics.views).toEqual({ sum: 1500, covers: 2 }); // c's Instagram post has no views
  });

  it('combines character and platform; "all" is no filter', () => {
    expect(postedTotals(library, { character: 'franz', platform: 'instagram' }).posts).toBe(2);
    expect(postedTotals(library, { character: 'all', platform: 'all' })).toEqual(postedTotals(library));
  });

  it('a video posted on two platforms is one video', () => {
    expect(postedTotals([library[0]]).videos).toBe(1);
  });

  it('with nothing posted for the filter: no videos, no posts, every sum null', () => {
    const t = postedTotals(library, { character: 'reginald' });
    expect(t).toEqual({
      videos: 0, posts: 0,
      metrics: {
        views: { sum: null, covers: 0 }, likes: { sum: null, covers: 0 }, comments: { sum: null, covers: 0 },
        shares: { sum: null, covers: 0 }, saves: { sum: null, covers: 0 },
      },
    });
    expect(postedTotals([]).videos).toBe(0);
  });
});

describe('scopeLine', () => {
  it('names the filter in words', () => {
    expect(scopeLine('all', 'all', () => 'x')).toBe('All characters, any platform');
    expect(scopeLine('franz', 'tiktok', (s) => (s === 'franz' ? 'Franz' : s))).toBe('Franz, TikTok');
    expect(scopeLine('franz', 'all', () => 'Franz')).toBe('Franz, any platform');
    expect(scopeLine('all', 'instagram', () => 'x')).toBe('All characters, Instagram');
  });
});
