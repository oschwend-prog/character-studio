// "Account per day" (owner 2026-10-15): the account's daily totals from Postiz (`studio metrics accounts`, runs of kind account_daily)
// beside the views of the character's Reels, over the last 7 London days. The pure part: reading the rows, the week's lines and
// the sparkline's geometry.
import { describe, expect, it } from 'vitest';
import { accountPerDay, handleKey, parseAccountDays, sparkSegments, type AccountDay } from './accountday';
import type { ViewsDay } from './types';

// 20 Oct 2026, 12:00 UTC = 13:00 in London (BST): the London day is the 20th.
const NOW = Date.parse('2026-10-20T12:00:00Z');

const row = (day: unknown, accounts: unknown) => ({ details: { day, accounts } });
const ig = (views: number, reach: number, replies: number) => ({ views, reach, replies });

describe('parseAccountDays', () => {
  it('reads the days of the runs, oldest first, keeping only the numbers it knows', () => {
    const got = parseAccountDays([
      row('2026-10-20', { '@franz.ig': { views: 176, reach: 130, likes: 15, replies: 7, bogus: 9 } }),
      row('2026-10-19', { '@franz.ig': ig(120, 90, 5) }),
    ]);
    expect(got.map((d) => d.day)).toEqual(['2026-10-19', '2026-10-20']);
    expect(got[1].accounts['@franz.ig']).toEqual({ views: 176, reach: 130, likes: 15, replies: 7 });
  });

  it('skips a run with no usable day or accounts, and a number that is not a plain count', () => {
    const got = parseAccountDays([
      null,
      undefined,
      { details: null },
      { details: 'text' },
      row('yesterday', { '@a': ig(1, 1, 1) }),
      row('2026-10-18', 'nope'),
      row('2026-10-17', { '@a': 'nope', '@b': { views: '12', reach: -3, replies: NaN, likes: 4 } }),
    ]);
    expect(got).toEqual([{ day: '2026-10-17', accounts: { '@b': { likes: 4 } } }]); // "12" is a string, -3 and NaN are no counts
  });

  it('two runs of one day join, the later run winning per handle', () => {
    const got = parseAccountDays([
      row('2026-10-20', { '@a': ig(1, 1, 1), '@b': ig(5, 5, 5) }),
      row('2026-10-20', { '@a': ig(9, 9, 9) }),
    ]);
    expect(got).toHaveLength(1);
    expect(got[0].accounts).toEqual({ '@a': ig(9, 9, 9), '@b': ig(5, 5, 5) });
  });

  it('nothing at all is an empty list', () => {
    expect(parseAccountDays([])).toEqual([]);
  });
});

describe('handleKey', () => {
  it('ignores case, spaces and the @', () => {
    expect(handleKey(' @Franz.IG ')).toBe('franz.ig');
    expect(handleKey('franz.ig')).toBe('franz.ig');
  });
});

const days: AccountDay[] = [
  { day: '2026-10-14', accounts: { '@franz.ig': ig(100, 70, 2) } },
  { day: '2026-10-18', accounts: { '@franz.ig': ig(300, 200, 6), '@franz.tt': { views: 50 } } },
  { day: '2026-10-19', accounts: { '@franz.ig': ig(120, 90, 5), '@someone.else': ig(9999, 9999, 9999) } },
  { day: '2026-10-20', accounts: { '@franz.ig': ig(176, 130, 7) } },
];
const reels = (day: string, views: number, slug = 'franz'): ViewsDay => ({ character_slug: slug, day, views, follows: 0 });

describe('accountPerDay', () => {
  it('lists the last 7 London days, oldest first, today last and called Today', () => {
    const m = accountPerDay('franz', ['@franz.ig'], days, [], NOW);
    expect(m.rows.map((r) => r.day)).toEqual([
      '2026-10-14', '2026-10-15', '2026-10-16', '2026-10-17', '2026-10-18', '2026-10-19', '2026-10-20',
    ]);
    expect(m.rows.map((r) => r.today)).toEqual([false, false, false, false, false, false, true]);
    expect(m.rows[6].label).toBe('Today');
    expect(m.rows[0].label).toBe('Wed 14 Oct');
  });

  it('puts the days of the account in views, reach and replies, and leaves a day without a reading empty (null, not 0)', () => {
    const m = accountPerDay('franz', ['@franz.ig'], days, [], NOW);
    expect(m.rows[0]).toMatchObject({ views: 100, reach: 70, replies: 2 });
    expect(m.rows[1]).toMatchObject({ views: null, reach: null, replies: null, reels: null, rest: null });
    expect(m.rows[6]).toMatchObject({ views: 176, reach: 130, replies: 7 });
  });

  it('adds up the character\'s own accounts and never another one\'s; a field only some accounts report is summed over those', () => {
    const m = accountPerDay('franz', ['@franz.ig', '@Franz.TT'], days, [], NOW);
    expect(m.rows[4]).toMatchObject({ views: 350, reach: 200, replies: 6 }); // the TikTok account gave views only
    expect(m.rows[5].views).toBe(120); // @someone.else is not his
    expect(m.counted).toEqual(['@franz.ig', '@Franz.TT']);
  });

  it('names only the accounts that have a reading in the week as counted', () => {
    const m = accountPerDay('franz', ['@franz.ig', '@franz.tt', '@never.read', null, undefined], days.slice(0, 1), [], NOW);
    expect(m.counted).toEqual(['@franz.ig']);
  });

  it('a day older than the 7 shown is not in the week', () => {
    const m = accountPerDay('franz', ['@franz.ig'], [{ day: '2026-10-13', accounts: { '@franz.ig': ig(1, 1, 1) } }], [], NOW);
    expect(m.hasData).toBe(false);
  });

  it('puts the views his posts gained that day in Reels and what is left in Rest, never below 0', () => {
    const m = accountPerDay(
      'franz', ['@franz.ig'], days,
      [reels('2026-10-20', 100), reels('2026-10-19', 500), reels('2026-10-18', 120, 'lenny'), reels('2026-10-14', 40)],
      NOW,
    );
    expect(m.rows[6]).toMatchObject({ reels: 100, rest: 76 }); // 176 - 100
    expect(m.rows[5]).toMatchObject({ reels: 500, rest: 0 }); // more Reels than account: 0, not -380
    expect(m.rows[4]).toMatchObject({ reels: null, rest: 300 }); // nobody measured his Reels that day (Lenny's do not count)
    expect(m.rows[0]).toMatchObject({ reels: 40, rest: 60 });
  });

  it('a recount that made a day negative is read as 0', () => {
    const m = accountPerDay('franz', ['@franz.ig'], days, [reels('2026-10-20', -30)], NOW);
    expect(m.rows[6]).toMatchObject({ reels: 0, rest: 176 });
  });

  it('a day with Reels but no account reading shows the Reels and no Rest', () => {
    const m = accountPerDay('franz', ['@franz.ig'], days, [reels('2026-10-16', 80)], NOW);
    expect(m.rows[2]).toMatchObject({ views: null, reels: 80, rest: null });
  });

  it('adds the week up: the totals of each column (rest being the sum of the days\' rests)', () => {
    const m = accountPerDay('franz', ['@franz.ig'], days, [reels('2026-10-20', 100), reels('2026-10-19', 500)], NOW);
    expect(m.total).toEqual({ views: 100 + 300 + 120 + 176, reach: 70 + 200 + 90 + 130, replies: 2 + 6 + 5 + 7, reels: 600, rest: 100 + 300 + 0 + 76 });
  });

  it('has no data without a reading in the week, and its totals are null, not 0', () => {
    const m = accountPerDay('franz', ['@franz.ig'], [], [reels('2026-10-20', 5)], NOW);
    expect(m.hasData).toBe(false);
    expect(m.total).toEqual({ views: null, reach: null, replies: null, reels: 5, rest: null });
    expect(m.counted).toEqual([]);
  });

  it('a character with no handle has no data', () => {
    expect(accountPerDay('franz', [null, undefined, ''], days, [], NOW).hasData).toBe(false);
  });

  it('takes today from the London clock: just after midnight in BST is already the next day', () => {
    const late = Date.parse('2026-10-20T23:30:00Z'); // 00:30 on the 21st in London
    const m = accountPerDay('franz', ['@franz.ig'], days, [], late);
    expect(m.rows[6].day).toBe('2026-10-21');
    expect(m.rows[0].day).toBe('2026-10-15');
  });

  it('the sparkline follows the account\'s views per day', () => {
    const m = accountPerDay('franz', ['@franz.ig'], days, [], NOW);
    expect(m.views).toEqual([100, null, null, null, 300, 120, 176]);
  });
});

describe('sparkSegments', () => {
  it('draws one polyline per run of days with a number, the biggest at the top and 0 at the bottom', () => {
    const g = sparkSegments([0, 10, null, 5], 64, 20, 2);
    expect(g.segments).toEqual(['2,18 22,2', '62,10']);
    expect(g.max).toBe(10);
  });

  it('a lone day is a dot, not a line: its segment holds one point and the last point is the newest number', () => {
    const g = sparkSegments([null, null, 4], 64, 20, 2);
    expect(g.segments).toEqual(['62,2']);
    expect(g.last).toEqual({ x: 62, y: 2 });
  });

  it('all zero draws a flat line at the bottom, nothing at all draws nothing', () => {
    expect(sparkSegments([0, 0], 64, 20, 2).segments).toEqual(['2,18 62,18']);
    const none = sparkSegments([null, null], 64, 20, 2);
    expect(none.segments).toEqual([]);
    expect(none.last).toBeNull();
  });
});
