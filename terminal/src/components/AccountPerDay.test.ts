// The "Account per day" block on a character's page (owner 2026-10-15): the last 7 London days of his accounts' REACH beside the views of
// his Reels, a small sparkline of the reach, Instagram's 7-day total of the account's views (read when, what his Reels gained in the
// same days, the rest, then likes, comments, replies), one plain line about the Stories and the 7-day views, and an empty state before
// the first reading. (Verified live: only reach is per day; the views are one total over the last 7 days.)
import { createElement } from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, it } from 'vitest';
import { accountPerDay, type AccountDay } from '../lib/accountday';
import type { ViewsDay } from '../lib/types';
import { AccountPerDayCard, windowSmallFigures, type ReelsAllTime } from './AccountPerDay';

const NOW = Date.parse('2026-10-20T12:00:00Z'); // the 20th in London
const READ_AT = Date.parse('2026-10-20T09:30:00Z'); // 2.5 hours before NOW

const days: AccountDay[] = [
  { day: '2026-10-18', accounts: { '@franz.ig': { reach: 900 } } },
  { day: '2026-10-19', accounts: { '@franz.ig': { reach: 1234 } } },
  {
    day: '2026-10-20',
    accounts: { '@franz.ig': { reach: 130 } },
    window: { days: 7, readAt: READ_AT, accounts: { '@franz.ig': { views: 1530, likes: 40, comments: 6, replies: 0 } } },
  },
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

  it('heads the table Day, Reach and Reels only, with scope on every header: no per-day Views, Rest or Replies', () => {
    const out = html();
    const head = out.match(/<thead>[\s\S]*<\/thead>/)?.[0] ?? '';
    expect([...head.matchAll(/<span class="label">([^<]*)<\/span>/g)].map((m) => m[1])).toEqual(['Day', 'Reach', 'Reels']);
    expect(head).not.toMatch(/>(Views|Rest|Replies)</);
    expect(out).toMatch(/<th scope="col"[^>]*>/);
    expect(out).toContain('<caption class="sr-only">');
  });

  it('shows the reach compactly and a dash where a day has none, never 0', () => {
    const out = html();
    expect(out).toContain('1.2K'); // 1234 reach on the 19th
    expect(out).toContain('900');
    expect(out).toContain('130');
    expect(out).toContain('—'); // days with no reading
  });

  it('shows the Reels of a day next to its reach', () => {
    const today = html().match(/<tr class="apd-today">[\s\S]*?<\/tr>/)?.[0] ?? '';
    expect(today).toContain('>130<'); // reach
    expect(today).toContain('>100<'); // what his Reels gained that day
  });

  it('adds the Reels up in the 7-day row, but not the reach (the same person can be reached on several days)', () => {
    const foot = html().match(/<tfoot>[\s\S]*<\/tfoot>/)?.[0] ?? '';
    expect(foot).toContain('>120<'); // 100 + 20
    expect(foot).not.toContain('2.3K'); // 900 + 1234 + 130 is not shown
    expect(foot).toContain('not added up');
  });

  it('says in plain lines that reach is per day, that the views are Instagram\'s 7-day total with the Stories, and why', () => {
    const out = html();
    expect(out).toContain('Account views are Instagram’s total for the last 7 days, Stories included');
    expect(out).toContain('no numbers for a single Story');
    expect(out).toContain('Reach is per day');
    expect(out).not.toContain('Story views are in the account totals'); // the old claim, that the views were per day
  });

  it('names the accounts that are added up', () => {
    const out = html();
    expect(out).toContain('@franz.ig');
    expect(out).not.toContain('@franz.tt'); // never read: not counted
  });

  it('draws a sparkline of the account\'s reach in his colour, labelled for a screen reader, with an end marker', () => {
    const out = html();
    expect(out).toMatch(/<svg[^>]*role="img"[^>]*aria-label="Account reach per day, last 7 days: [^"]*130[^"]*"/);
    expect(out).toContain('stroke="var(--series-franz)"');
    expect(out).toContain('<circle');
  });

  it('keeps the text in ink colours: the series colour is only on the sparkline', () => {
    const out = html();
    expect(out.match(/var\(--series-franz\)/g)?.length).toBeGreaterThan(0);
    expect(out.replace(/<svg[\s\S]*?<\/svg>/g, '')).not.toContain('--series-');
  });

  it('shows "Account views, last 7 days" as the window total, when it was read, and the figures of the window', () => {
    const out = html();
    expect(out).toMatch(/Account views, last 7 days<\/span><span class="v">1\.5K<\/span>/);
    expect(out).toContain('read 2h ago');
    expect(out).toContain('Likes 40 · Comments 6 · Replies 0'); // a real 0 is shown
  });

  it('says what his Reels gained in the same 7 days and the rest, when both are known', () => {
    const out = html();
    expect(out).toContain('Reels gained 120 in the same 7 days · rest 1.4K (Stories, older posts)'); // 1530 - 120 = 1410
  });

  it('leaves the Reels-and-rest line out when the rest is not known or would be negative', () => {
    const noReels = html(accountPerDay('franz', ['@franz.ig'], days, [], NOW));
    expect(noReels).toContain('1.5K');
    expect(noReels).not.toContain('in the same 7 days');
    const tooMany = html(accountPerDay('franz', ['@franz.ig'], days, [{ ...reels[0], views: 9000 }], NOW));
    expect(tooMany).not.toContain('in the same 7 days');
    expect(tooMany).not.toContain('rest ');
  });

  it('leaves out a small figure that was not reported, never shows it as 0', () => {
    const w = accountPerDay('franz', ['@franz.ig'], [{ day: '2026-10-20', accounts: {}, window: { days: 7, readAt: READ_AT, accounts: { '@franz.ig': { views: 5, likes: 2 } } } }], [], NOW).window!;
    expect(windowSmallFigures(w)).toBe('Likes 2');
    const none = accountPerDay('franz', ['@franz.ig'], [{ day: '2026-10-20', accounts: {}, window: { days: 7, readAt: READ_AT, accounts: { '@franz.ig': { views: 5 } } } }], [], NOW).window!;
    expect(windowSmallFigures(none)).toBe('');
  });

  it('with reach but no window yet shows a dash for the account views, not 0', () => {
    const out = html(accountPerDay('franz', ['@franz.ig'], days.slice(0, 2), reels, NOW));
    expect(out).toMatch(/Account views, last 7 days<\/span><span class="v"><span[^>]*>—<\/span>/);
    expect(out).not.toContain('>read '); // no "read 2h ago" line without a window
  });

  it('with a window but no reach the table still shows, and there is no sparkline', () => {
    const only: AccountDay[] = [{ day: '2026-10-20', accounts: {}, window: { days: 7, readAt: READ_AT, accounts: { '@franz.ig': { views: 334 } } } }];
    const out = html(accountPerDay('franz', ['@franz.ig'], only, reels, NOW));
    expect(out).toContain('<table');
    expect(out).not.toContain('<svg');
    expect(out).toMatch(/Account views, last 7 days<\/span><span class="v">334</);
  });

  it('shows the Reels views of all time, with how many posts that covers', () => {
    const out = html(undefined, { views: { sum: 41_200, covers: 18 }, posts: 20 });
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
