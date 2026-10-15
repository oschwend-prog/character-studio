// The totals strip on Characters → "All videos" (owner 2026-10-15): posted videos and the sum of their latest views, likes, comments,
// shares and saves for the current filter, each sum saying how many posts it covers.
import { createElement } from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, it } from 'vitest';
import { postedTotals, type PostedTotals } from '../lib/totals';
import type { LibraryClip, LibraryPost } from '../lib/types';
import { TotalsStrip } from './TotalsStrip';

const post = (over: Partial<LibraryPost> = {}): LibraryPost => ({
  post_id: Math.random().toString(36).slice(2), platform: 'instagram', handle: '@franz.ig', status: 'posted',
  scheduled_for: '2026-10-14T18:00:00Z', url: null, views: null, likes: null, comments: null, shares: null, saves: null, captured_at: null,
  ...over,
});
const clip = (id: string, posts: LibraryPost[]): LibraryClip => ({
  id, character_slug: 'franz', character_name: 'Franz', mode: 'dropin', state: 'posted', hook: null, caption: null, master_path: null,
  reject_reason: null, created_at: '2026-10-14T10:00:00Z', cost_credits: null, outlier_x: null, format_id: null, posts,
  platforms: [...new Set(posts.map((p) => p.platform))], views: null, posted_at: null,
});

const totals: PostedTotals = postedTotals([
  clip('a', [post({ views: 1000, likes: 100, comments: 10, shares: 5, saves: 20 }), post({ platform: 'tiktok', views: 4000, likes: 300 })]),
  clip('b', [post({ views: 1234 })]),
  clip('c', [post()]), // posted, never measured
]);

const html = (t: PostedTotals = totals, capped = false) =>
  renderToStaticMarkup(createElement(TotalsStrip, { totals: t, scope: 'Franz, any platform', capped }));

describe('TotalsStrip', () => {
  it('says whose totals these are and shows the six figures, each with its label', () => {
    const out = html();
    expect(out).toContain('Franz, any platform');
    for (const label of ['Videos posted', 'Views', 'Likes', 'Comments', 'Shares', 'Saves']) expect(out).toContain(`>${label}<`);
  });

  it('shows the posted videos and the compact sums', () => {
    const out = html();
    expect(out).toMatch(/Videos posted<\/span><span class="v">3</); // a, b, c
    expect(out).toMatch(/Views<\/span><span class="v">6\.2K</); // 1000 + 4000 + 1234 = 6234
    expect(out).toMatch(/Likes<\/span><span class="v">400</);
  });

  it('says how many posts each sum covers, never more than it has', () => {
    const out = html();
    expect(out).toContain('3 of 4 posts'); // 4 posts are posted, 3 have views
    expect(out).toContain('2 of 4 posts'); // likes: two posts
    expect(out).toContain('1 of 4 posts'); // comments, shares, saves: one post each
  });

  it('a figure no post has is a dash, not 0', () => {
    const out = html(postedTotals([clip('x', [post({ views: 10 })])]));
    expect(out).toMatch(/Likes<\/span><span class="v"><span[^>]*>—<\/span><\/span>/);
    expect(out).not.toMatch(/Likes<\/span><span class="v">0</);
    expect(out).toContain('none measured');
  });

  it('explains in one plain line that a missing figure is left out and not counted as 0', () => {
    expect(html()).toContain('left out, never counted as 0');
  });

  it('says when the library is cut at the newest clips', () => {
    expect(html(totals, true)).toContain('newest 300 clips');
    expect(html(totals, false)).not.toContain('newest 300 clips');
  });

  it('with no posted video for the filter shows one muted line and no figures', () => {
    const out = html(postedTotals([]));
    expect(out).toContain('No posted videos for this filter yet');
    expect(out).not.toContain('Likes');
  });

  it('keeps the numbers in ink colours: no series colour, no inline colour at all', () => {
    expect(html()).not.toMatch(/--series-|style="[^"]*color/);
  });
});
