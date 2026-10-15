// "Account per day" (owner 2026-10-15): the account's figures from Postiz (`studio metrics accounts`, runs of kind account_daily)
// beside the views of the character's Reels, over the last 7 London days. Only reach is per day (verified live); the account's views,
// likes, comments and replies are Instagram's ONE total over the last 7 days, stored as details.window on the row of the day it was
// read. The pure part: reading the rows, the week's lines, the window and the sparkline's geometry.
import { describe, expect, it } from 'vitest';
import { accountPerDay, handleKey, parseAccountDays, sparkSegments, type AccountDay } from './accountday';
import type { ViewsDay } from './types';

// 20 Oct 2026, 12:00 UTC = 13:00 in London (BST): the London day is the 20th.
const NOW = Date.parse('2026-10-20T12:00:00Z');
const READ_AT = '2026-10-20T10:30:00+01:00'; // 09:30 UTC, 2.5 hours before NOW

const row = (day: unknown, accounts: unknown, window?: unknown) => ({ details: { day, accounts, ...(window === undefined ? {} : { window }) } });
const reach = (n: number) => ({ reach: n });

describe('parseAccountDays', () => {
  it('reads the days of the runs, oldest first, keeping only the numbers it knows', () => {
    const got = parseAccountDays([
      row('2026-10-20', { '@franz.ig': { reach: 130, views: 5, bogus: 9 } }),
      row('2026-10-19', { '@franz.ig': reach(90) }),
    ]);
    expect(got.map((d) => d.day)).toEqual(['2026-10-19', '2026-10-20']);
    expect(got[1].accounts['@franz.ig']).toEqual({ reach: 130, views: 5 });
    expect(got[1].window).toBeUndefined();
  });

  it('reads the window of a run: its days, when it was read, and the totals per account', () => {
    const got = parseAccountDays([
      row('2026-10-20', {}, { days: 7, read_at: READ_AT, accounts: { '@franz.ig': { views: 334, likes: 1, comments: 2, shares: 0, saves: 0, replies: 0, bogus: 3 } } }),
    ]);
    expect(got).toEqual([
      {
        day: '2026-10-20',
        accounts: {}, // a row that holds only the window has no daily figure yet
        window: {
          days: 7,
          readAt: Date.parse(READ_AT),
          accounts: { '@franz.ig': { views: 334, likes: 1, comments: 2, shares: 0, saves: 0, replies: 0 } }, // real zeros kept
        },
      },
    ]);
  });

  it('a window with no usable time or length still counts: 7 days, read at an unknown time', () => {
    const got = parseAccountDays([row('2026-10-20', {}, { days: 'seven', read_at: 'yesterday', accounts: { '@a': { views: 4 } } })]);
    expect(got[0].window).toEqual({ days: 7, readAt: null, accounts: { '@a': { views: 4 } } });
  });

  it('skips a run with no usable day, or with neither a daily figure nor a window, and a number that is not a plain count', () => {
    const got = parseAccountDays([
      null,
      undefined,
      { details: null },
      { details: 'text' },
      row('yesterday', { '@a': reach(1) }),
      row('2026-10-18', 'nope'),
      row('2026-10-16', {}, { days: 7, read_at: READ_AT, accounts: 'nope' }), // a window without an account
      row('2026-10-15', {}, { days: 7, read_at: READ_AT, accounts: { '@a': { views: '12' } } }), // a string is no count
      row('2026-10-17', { '@a': 'nope', '@b': { reach: '12', views: -3, replies: NaN, likes: 4 } }),
    ]);
    expect(got).toEqual([{ day: '2026-10-17', accounts: { '@b': { likes: 4 } } }]); // "12" is a string, -3 and NaN are no counts
  });

  it('two runs of one day join, the later run winning per handle, in the daily figures and in the window', () => {
    const got = parseAccountDays([
      row('2026-10-20', { '@a': reach(1), '@b': reach(5) }, { days: 7, read_at: READ_AT, accounts: { '@a': { views: 1 }, '@b': { views: 5 } } }),
      row('2026-10-20', { '@a': reach(9) }, { days: 7, read_at: '2026-10-20T08:00:00+01:00', accounts: { '@a': { views: 9 } } }),
    ]);
    expect(got).toHaveLength(1);
    expect(got[0].accounts).toEqual({ '@a': reach(9), '@b': reach(5) });
    expect(got[0].window?.accounts).toEqual({ '@a': { views: 9 }, '@b': { views: 5 } });
    expect(got[0].window?.readAt).toBe(Date.parse(READ_AT)); // the latest read time
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

const window = (accounts: AccountDay['accounts'], readAt: number | null = Date.parse(READ_AT)) => ({ days: 7, readAt, accounts });
const days: AccountDay[] = [
  { day: '2026-10-14', accounts: { '@franz.ig': reach(70) } },
  { day: '2026-10-18', accounts: { '@franz.ig': reach(200), '@franz.tt': reach(50) } },
  { day: '2026-10-19', accounts: { '@franz.ig': reach(90), '@someone.else': reach(9999) } },
  {
    day: '2026-10-20',
    accounts: { '@franz.ig': reach(130) },
    window: window({ '@franz.ig': { views: 1530, likes: 40, comments: 6, replies: 7 }, '@someone.else': { views: 99_999, likes: 99 } }),
  },
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

  it('puts the reach of the account on each day, and leaves a day without a reading empty (null, not 0)', () => {
    const m = accountPerDay('franz', ['@franz.ig'], days, [], NOW);
    expect(m.rows.map((r) => r.reach)).toEqual([70, null, null, null, 200, 90, 130]);
    expect(m.rows[1]).toMatchObject({ reach: null, reels: null });
    expect(m.reach).toEqual([70, null, null, null, 200, 90, 130]); // the sparkline follows the reach per day
  });

  it('a real 0 reach is a 0, not a missing reading', () => {
    const m = accountPerDay('franz', ['@franz.ig'], [{ day: '2026-10-20', accounts: { '@franz.ig': reach(0) } }], [], NOW);
    expect(m.rows[6].reach).toBe(0);
    expect(m.hasData).toBe(true);
  });

  it('has no per-day views, replies or rest: they are not per day', () => {
    const m = accountPerDay('franz', ['@franz.ig'], days, [reels('2026-10-20', 100)], NOW);
    expect(Object.keys(m.rows[6]).sort()).toEqual(['day', 'label', 'reach', 'reels', 'today']);
  });

  it('a row of the first version (views stored as that day\'s) shows no views anywhere: only the reach counts per day', () => {
    const old: AccountDay[] = [{ day: '2026-10-20', accounts: { '@franz.ig': { views: 334, likes: 1, comments: 2, replies: 0 } } }];
    const m = accountPerDay('franz', ['@franz.ig'], old, [], NOW);
    expect(m.rows[6].reach).toBeNull();
    expect(m.window).toBeNull();
    expect(m.hasData).toBe(false);
  });

  it('adds up the character\'s own accounts and never another one\'s', () => {
    const m = accountPerDay('franz', ['@franz.ig', '@Franz.TT'], days, [], NOW);
    expect(m.rows[4].reach).toBe(250); // 200 + 50
    expect(m.rows[5].reach).toBe(90); // @someone.else is not his
    expect(m.counted).toEqual(['@franz.ig', '@Franz.TT']);
  });

  it('names only the accounts that have a reading in the week as counted', () => {
    const m = accountPerDay('franz', ['@franz.ig', '@franz.tt', '@never.read', null, undefined], days.slice(0, 1), [], NOW);
    expect(m.counted).toEqual(['@franz.ig']);
  });

  it('counts an account that is only in the window', () => {
    const m = accountPerDay('franz', ['@franz.ig', '@franz.tt'], [{ day: '2026-10-20', accounts: {}, window: window({ '@franz.tt': { views: 7 } }) }], [], NOW);
    expect(m.counted).toEqual(['@franz.tt']);
  });

  it('a day older than the 7 shown is not in the week', () => {
    const m = accountPerDay('franz', ['@franz.ig'], [{ day: '2026-10-13', accounts: { '@franz.ig': reach(1) } }], [], NOW);
    expect(m.hasData).toBe(false);
  });

  it('puts the views his posts gained that day in Reels (his rows only, a negative recount read as 0) and adds the week up', () => {
    const m = accountPerDay(
      'franz', ['@franz.ig'], days,
      [reels('2026-10-20', 100), reels('2026-10-19', 500), reels('2026-10-18', 120, 'lenny'), reels('2026-10-14', 40), reels('2026-10-16', -30)],
      NOW,
    );
    expect(m.rows.map((r) => r.reels)).toEqual([40, null, 0, null, null, 500, 100]);
    expect(m.reelsWeek).toBe(640);
  });

  it('nobody measured his Reels in the week: Reels are null, not 0', () => {
    const m = accountPerDay('franz', ['@franz.ig'], days, [reels('2026-10-20', 5, 'lenny')], NOW);
    expect(m.reelsWeek).toBeNull();
  });

  it('a day with Reels but no account reading shows the Reels and no reach', () => {
    const m = accountPerDay('franz', ['@franz.ig'], days, [reels('2026-10-16', 80)], NOW);
    expect(m.rows[2]).toMatchObject({ reach: null, reels: 80 });
  });

  it('has no data without a reading in the week, and no window', () => {
    const m = accountPerDay('franz', ['@franz.ig'], [], [reels('2026-10-20', 5)], NOW);
    expect(m.hasData).toBe(false);
    expect(m.window).toBeNull();
    expect(m.reelsWeek).toBe(5);
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
});

describe('accountPerDay: the window', () => {
  it('is the newest window read for his accounts, summed over his handles only, with when it was read', () => {
    const m = accountPerDay('franz', ['@franz.ig'], days, [], NOW);
    expect(m.window).toMatchObject({ views: 1530, likes: 40, comments: 6, replies: 7, days: 7, readAt: Date.parse(READ_AT), readAgo: '2h ago' });
    expect(m.hasData).toBe(true);
  });

  it('adds his accounts up: a figure only some of them report is summed over those', () => {
    const both: AccountDay[] = [
      { day: '2026-10-20', accounts: {}, window: window({ '@franz.ig': { views: 300, likes: 4 }, '@franz.tt': { views: 50 }, '@someone.else': { views: 9 } }) },
    ];
    const m = accountPerDay('franz', ['@franz.ig', '@Franz.TT'], both, [], NOW);
    expect(m.window).toMatchObject({ views: 350, likes: 4, comments: null, replies: null }); // null, never 0, where nobody reported
  });

  it('keeps a real 0 (a window with no likes is 0 likes)', () => {
    const zero: AccountDay[] = [{ day: '2026-10-20', accounts: {}, window: window({ '@franz.ig': { views: 12, likes: 0, comments: 0, replies: 0 } }) }];
    expect(accountPerDay('franz', ['@franz.ig'], zero, [], NOW).window).toMatchObject({ views: 12, likes: 0, comments: 0, replies: 0 });
  });

  it('takes the newest window, not an older one, and skips a newer one that holds none of his accounts', () => {
    const many: AccountDay[] = [
      { day: '2026-10-17', accounts: {}, window: window({ '@franz.ig': { views: 111 } }) },
      { day: '2026-10-19', accounts: {}, window: window({ '@franz.ig': { views: 222 } }) },
      { day: '2026-10-20', accounts: {}, window: window({ '@someone.else': { views: 999 } }) },
    ];
    expect(accountPerDay('franz', ['@franz.ig'], many, [], NOW).window?.views).toBe(222);
  });

  it('says how long ago it was read, or nothing when the time is unknown', () => {
    const d = (readAt: number | null): AccountDay[] => [{ day: '2026-10-20', accounts: {}, window: window({ '@franz.ig': { views: 1 } }, readAt) }];
    expect(accountPerDay('franz', ['@franz.ig'], d(NOW - 5 * 60_000), [], NOW).window?.readAgo).toBe('5m ago');
    expect(accountPerDay('franz', ['@franz.ig'], d(null), [], NOW).window).toMatchObject({ readAt: null, readAgo: null });
  });

  it('holds what his Reels gained over the same 7 days and the rest: window views minus those Reels', () => {
    const m = accountPerDay('franz', ['@franz.ig'], days, [reels('2026-10-20', 100), reels('2026-10-19', 20), reels('2026-10-10', 5000)], NOW);
    expect(m.window).toMatchObject({ views: 1530, reels: 120, rest: 1410 }); // 5000 on the 10th is outside the 7 days
  });

  it('the rest is never negative: when the Reels gained more than the window, there is no rest', () => {
    const m = accountPerDay('franz', ['@franz.ig'], days, [reels('2026-10-20', 4000)], NOW);
    expect(m.window).toMatchObject({ views: 1530, reels: 4000, rest: null });
  });

  it('the rest is exactly 0 when the Reels gained all of it', () => {
    const m = accountPerDay('franz', ['@franz.ig'], days, [reels('2026-10-20', 1530)], NOW);
    expect(m.window?.rest).toBe(0);
  });

  it('no Reels measured or no window views: no rest', () => {
    expect(accountPerDay('franz', ['@franz.ig'], days, [], NOW).window).toMatchObject({ reels: null, rest: null });
    const noViews: AccountDay[] = [{ day: '2026-10-20', accounts: {}, window: window({ '@franz.ig': { likes: 3 } }) }];
    expect(accountPerDay('franz', ['@franz.ig'], noViews, [reels('2026-10-20', 9)], NOW).window).toMatchObject({ views: null, likes: 3, rest: null });
  });

  it('a window alone is data (reach has no reading yet)', () => {
    const only: AccountDay[] = [{ day: '2026-10-20', accounts: {}, window: window({ '@franz.ig': { views: 334 } }) }];
    const m = accountPerDay('franz', ['@franz.ig'], only, [], NOW);
    expect(m.hasData).toBe(true);
    expect(m.reach).toEqual([null, null, null, null, null, null, null]);
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
