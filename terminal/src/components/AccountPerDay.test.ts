// The "Account per day" block on a character's page (owner 2026-10-15): the last 7 London days of his accounts' views, reach and
// replies beside the views of his Reels, a small sparkline of the account's views, one plain line about the Stories, and an empty
// state before the first reading.
import { createElement } from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, it } from 'vitest';
import { accountPerDay, type AccountDay } from '../lib/accountday';
import type { ViewsDay } from '../lib/types';
import { AccountPerDayCard, type ReelsAllTime } from './AccountPerDay';

const NOW = Date.parse('2026-10-20T12:00:00Z'); // the 20th in London

const days: AccountDay[] = [
  { day: '2026-10-18', accounts: { '@franz.ig': { views: 1234, reach: 900, replies: 6 } } },
  { day: '2026-10-19', accounts: { '@franz.ig': { views: 120, reach: 90 } } }, // no replies reported that day
  { day: '2026-10-20', accounts: { '@franz.ig': { views: 176, reach: 130, replies: 7 } } },
];
const reels: ViewsDay[] = [
  { character_slug: 'franz', day: '2026-10-20', views: 100, follows: 0 },
  { character_slug: 'franz', day: '2026-10-19', views: 20, follows: 0 },
];

const html = (model = accountPerDay('franz', ['@franz.ig', '@franz.tt'], days, reels, NOW), allTime?: ReelsAllTime) =>
  renderToStaticMarkup(createElement(AccountPerDayCard, { name: 'Franz', slug: 'franz', model, allTime }));

describe('AccountPerDayCard', () => {
  it('is a section called "Account per day" with one row per day of the week, today last, and a total', () => {
    const out = html();
    expect(out).toContain('Account per day');
    expect(out).toContain('Wed 14 Oct');
    expect(out).toContain('>Today<');
    expect((out.match(/<tbody>[\s\S]*<\/tbody>/)?.[0].match(/<tr/g) ?? []).length).toBe(7);
    expect(out).toContain('7 days');
  });

  it('heads the columns Views, Reach, Replies, Reels and Rest, with scope on every header', () => {
    const out = html();
    for (const label of ['Views', 'Reach', 'Replies', 'Reels', 'Rest']) expect(out).toContain(`>${label}<`);
    expect(out).toContain('Stories, older posts'); // what Rest is, in words
    expect(out.indexOf('>Views<')).toBeLessThan(out.indexOf('>Reach<')); // the comparison comes first
    expect(out.indexOf('>Rest<')).toBeLessThan(out.indexOf('>Reach<'));
    expect(out).toMatch(/<th scope="col"[^>]*>/);
    expect(out).toContain('<caption class="sr-only">');
  });

  it('shows the numbers compactly and a dash where a day has none, never 0', () => {
    const out = html();
    expect(out).toContain('1.2K'); // 1234 views on the 18th
    expect(out).toContain('176');
    expect(out).toContain('>76<'); // Rest on the 20th: 176 - 100
    expect(out).toContain('—'); // days with no reading, and the 19th's replies
  });

  it('says in one plain line that Story views are in the account totals and why', () => {
    const out = html();
    expect(out).toContain('Story views are in the account totals');
    expect(out).toContain('no numbers for a single Story');
  });

  it('names the accounts that are added up', () => {
    const out = html();
    expect(out).toContain('@franz.ig');
    expect(out).not.toContain('@franz.tt'); // never read: not counted
  });

  it('draws a sparkline of the account\'s views in his colour, labelled for a screen reader, with an end marker', () => {
    const out = html();
    expect(out).toMatch(/<svg[^>]*role="img"[^>]*aria-label="Account views per day, last 7 days: [^"]*"/);
    expect(out).toContain('stroke="var(--series-franz)"');
    expect(out).toContain('<circle');
  });

  it('keeps the text in ink colours: the series colour is only on the sparkline', () => {
    const out = html();
    expect(out.match(/var\(--series-franz\)/g)?.length).toBeGreaterThan(0);
    expect(out.replace(/<svg[\s\S]*?<\/svg>/g, '')).not.toContain('--series-');
  });

  it('shows the 7-day account total and the Reels views of all time, with how many posts that covers', () => {
    const out = html(undefined, { views: { sum: 41_200, covers: 18 }, posts: 20 });
    expect(out).toMatch(/Account views, 7 days<\/span><span class="v">1\.5K</); // 1234 + 120 + 176 = 1530
    expect(out).toContain('Reels 120 · rest 1.4K'); // 120 from his Reels, the other 1410 is Stories and older posts
    expect(out).toMatch(/Reels views, all time<\/span><span class="v">41\.2K</);
    expect(out).toContain('18 of 20 posts');
  });

  it('the all-time figure is a dash, not 0, when none of his posts has views', () => {
    const out = html(undefined, { views: { sum: null, covers: 0 }, posts: 3 });
    expect(out).toMatch(/Reels views, all time<\/span><span class="v"><span[^>]*>—<\/span>/);
    expect(out).toContain('none measured');
  });

  it('with nothing posted yet the all-time tile says so', () => {
    expect(html(undefined, { views: { sum: null, covers: 0 }, posts: 0 })).toContain('no posted videos yet');
  });

  it('without the all-time figure (no library yet) the block shows no all-time tile', () => {
    expect(html()).not.toContain('all time');
  });

  it('the all-time figure is shown in the empty state too: it does not depend on the account readings', () => {
    const out = html(accountPerDay('franz', ['@franz.ig'], [], [], NOW), { views: { sum: 900, covers: 2 }, posts: 2 });
    expect(out).toContain('No account numbers yet');
    expect(out).toMatch(/Reels views, all time<\/span><span class="v">900</);
  });

  it('with no reading in the week shows the empty state and no table', () => {
    const out = html(accountPerDay('franz', ['@franz.ig'], [], reels, NOW));
    expect(out).toContain('Account per day');
    expect(out).toContain('No account numbers yet');
    expect(out).not.toContain('<table');
    expect(out).not.toContain('<svg');
  });

  it('the empty state still says where the numbers come from', () => {
    const out = html(accountPerDay('franz', [], [], [], NOW));
    expect(out).toContain('every 6 hours');
  });
});
