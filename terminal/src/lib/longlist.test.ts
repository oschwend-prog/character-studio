import { describe, expect, it } from 'vitest';
import {
  DEFAULT_SORT, ageCell, ariaSort, compactCount, firstLine, longListCounts, longListRow, longListRows, nextSort, outlierCell, pickMode, picksView,
  sortLongList, type LongListRow,
} from './longlist';
import type { Pick } from './types';

const NOW = Date.parse('2026-10-06T12:00:00Z');
const DAY = 86_400_000;
const ago = (days: number) => new Date(NOW - days * DAY).toISOString();

let n = 0;
const pick = (over: Partial<Pick> = {}): Pick => {
  n += 1;
  return {
    id: `p${String(n).padStart(3, '0')}`, url: `https://www.tiktok.com/@a/video/${n}`, platform: 'tiktok', creator_handle: '@a', views: 1_000_000,
    outlier_x: 30, origin: 'scan', character_slug: 'biscuit', character_name: 'Biscuit', intended_character: null, total_score: 70,
    virality: 8, reach: 6, freshness: 7, fit: 8, feasibility: 7, saturation: 8, proposed_mode: 'dropin', hook: 'a hook', prop: null,
    concept: `Concept ${n}\nsecond line`, enhancement: null, needs: null, decision: null, hold_reason: null, note: null, status: 'new',
    created_at: new Date(NOW - 3600_000 + n * 1000).toISOString(), owner_note: null, owner_mode: null, owner_presence: null,
    posted_at: ago(3),
    ...over,
  };
};
const ids = (rows: LongListRow[]) => rows.map((r) => r.pick.id);

describe('compact numbers', () => {
  it('prints billions with two decimals, millions and thousands with one, and moves up a unit when it rounds over', () => {
    expect(compactCount(6_083_137_818)).toBe('6.08B');
    expect(compactCount(2_700_000)).toBe('2.7M');
    expect(compactCount(731_700)).toBe('731.7K');
    expect(compactCount(18_700_000)).toBe('18.7M');
    expect(compactCount(1_000_000_000)).toBe('1B');
    expect(compactCount(475_606_503)).toBe('475.6M');
    expect(compactCount(999_960)).toBe('1M');
    expect(compactCount(999_999_999)).toBe('1B');
    expect(compactCount(950)).toBe('950');
    expect(compactCount(0)).toBe('0');
    expect(compactCount(null)).toBe('—');
    expect(compactCount(Number.NaN)).toBe('—');
  });

  it('prints the outlier with a times sign', () => {
    expect([outlierCell(1809.6), outlierCell(18.24), outlierCell(5), outlierCell(null)]).toEqual(['1,810×', '18.2×', '5×', '—']);
  });
});

describe('the age and the title', () => {
  it('counts an iconic moment in years and anything else in days', () => {
    expect(ageCell('2012-07-15', 'iconic', NOW)?.label).toBe('14 y');
    expect(ageCell(ago(6), 'iconic', NOW)?.label).toBe('<1 y');
    expect(ageCell(ago(3.5), 'viral_now', NOW)?.label).toBe('3 d');
    expect(ageCell(ago(0.4), 'rising', NOW)?.label).toBe('<1 d');
    expect(ageCell(null, 'iconic', NOW)).toBeNull();
    expect(ageCell('last week', 'viral_now', NOW)).toBeNull();
  });

  it('takes the first line of the concept, else the hook, the creator or the URL', () => {
    expect(firstLine('  \n Hop and lasso \nsecond')).toBe('Hop and lasso');
    expect(firstLine(null)).toBeNull();
    expect(longListRow(pick({ concept: 'One line' }), NOW).title).toBe('One line');
    expect(longListRow(pick({ concept: null, hook: 'sausage style' }), NOW).title).toBe('“sausage style”');
    expect(longListRow(pick({ concept: null, hook: null, creator_handle: null }), NOW).title).toMatch(/^https:\/\/www\.tiktok\.com\//);
  });
});

describe('a long-list row', () => {
  it('shows an iconic moment by its original views and recognisability, anything else by its own views', () => {
    const iconic = longListRow(pick({ tier: 'iconic', views: 12_000, original_views: 6_083_137_818, recognisability: 10, posted_at: '2012-07-15' }), NOW);
    expect([iconic.tier, iconic.views, iconic.rec, iconic.age?.label]).toEqual(['iconic', 6_083_137_818, 10, '14 y']);
    const viral = longListRow(pick({ views: 5_800_000, original_views: 9e9, recognisability: 9, posted_at: ago(2), outlier_x: 1809.6 }), NOW);
    expect([viral.tier, viral.views, viral.rec, viral.age?.label, viral.outlier]).toEqual(['viral_now', 5_800_000, null, '2 d', 1809.6]);
    expect(viral.velocity).toBe(2_900_000); // views / days since posting
    expect(longListRow(pick({ velocity: 310_000 }), NOW).velocity).toBe(310_000); // the stored velocity wins
  });

  it('takes the analyst’s credits, else the estimate rule of the mode', () => {
    expect([longListRow(pick({ est_credits: 91 }), NOW).credits, longListRow(pick({ est_credits: 91 }), NOW).creditsEstimated]).toEqual([91, false]);
    const dropin = longListRow(pick({ proposed_mode: 'dropin' }), NOW);
    expect([dropin.credits, dropin.creditsEstimated, dropin.mode]).toEqual([91, true, 'dropin']);
    expect(longListRow(pick({ proposed_mode: 'recreate' }), NOW).credits).toBe(160);
    expect(longListRow(pick({ proposed_mode: 'dropin', owner_music: 'ai_beat' }), NOW).credits).toBe(121);
    expect(longListRow(pick({ proposed_mode: 'dropin', owner_mode: 'recreate' }), NOW).mode).toBe('recreate'); // the owner's mode wins
    expect(pickMode({ proposed_mode: 'something', owner_mode: null })).toBeNull();
  });
});

describe('the default order', () => {
  it('is tier first (Broke the internet on top, most recognisable first), then the score; the gallery last', () => {
    const g = pick({ gallery: true, total_score: 99 });
    const v1 = pick({ total_score: 72 });
    const v2 = pick({ total_score: 88 });
    const vNone = pick({ total_score: null });
    const r = pick({ posted_at: ago(2), outlier_x: 6, views: 50_000, total_score: 95 });
    const i1 = pick({ tier: 'iconic', recognisability: 8, total_score: 90 });
    const i2 = pick({ tier: 'iconic', recognisability: 10, total_score: 60 });
    const i3 = pick({ tier: 'iconic', recognisability: 10, total_score: 75 });
    const iNone = pick({ tier: 'iconic', recognisability: null, total_score: 99 });
    const rows = [g, v1, v2, vNone, r, i1, i2, i3, iNone].map((p) => longListRow(p, NOW));
    expect(ids(sortLongList(rows, DEFAULT_SORT))).toEqual([i3.id, i2.id, i1.id, iNone.id, v2.id, v1.id, vNone.id, r.id, g.id]);
  });
});

describe('sorting by a column', () => {
  const a = pick({ views: 3_000_000, total_score: 60, concept: 'banana' });
  const b = pick({ views: null, total_score: 80, concept: 'apple' });
  const c = pick({ views: 9_000_000, total_score: 70, concept: 'cherry' });
  const rows = [a, b, c].map((p) => longListRow(p, NOW));

  it('runs either way, and a row with no value stays last both ways', () => {
    expect(ids(sortLongList(rows, { key: 'views', dir: 'desc' }))).toEqual([c.id, a.id, b.id]);
    expect(ids(sortLongList(rows, { key: 'views', dir: 'asc' }))).toEqual([a.id, c.id, b.id]);
    expect(ids(sortLongList(rows, { key: 'score', dir: 'desc' }))).toEqual([b.id, c.id, a.id]);
    expect(ids(sortLongList(rows, { key: 'clip', dir: 'asc' }))).toEqual([b.id, a.id, c.id]);
  });

  it('flips the direction on a second tap, starts a new column in its own direction, and says so in aria-sort', () => {
    const s1 = nextSort(DEFAULT_SORT, 'views');
    expect(s1).toEqual({ key: 'views', dir: 'desc' });
    const s2 = nextSort(s1, 'views');
    expect(s2).toEqual({ key: 'views', dir: 'asc' });
    expect(nextSort(s2, 'age')).toEqual({ key: 'age', dir: 'asc' }); // the youngest first
    expect(nextSort(s2, 'clip')).toEqual({ key: 'clip', dir: 'asc' });
    expect([ariaSort(s1, 'views'), ariaSort(s2, 'views'), ariaSort(s2, 'score'), ariaSort(DEFAULT_SORT, 'tier')]).toEqual([
      'descending', 'ascending', 'none', 'none',
    ]);
  });
});

describe('the filters', () => {
  it('keeps new picks only, of one character and one tier, and counts the chips', () => {
    const roster = [{ slug: 'biscuit' }, { slug: 'reginald' }];
    const bi = pick({ tier: 'iconic' });
    const bv = pick();
    const rv = pick({ character_slug: 'reginald', character_name: 'Reginald' });
    const done = pick({ status: 'approved' });
    const all = [bi, bv, rv, done];
    expect(ids(longListRows(all, { character: 'all', tier: 'all' }, NOW)).sort()).toEqual([bi.id, bv.id, rv.id].sort());
    expect(ids(longListRows(all, { character: 'biscuit', tier: 'all' }, NOW)).sort()).toEqual([bi.id, bv.id].sort());
    expect(ids(longListRows(all, { character: 'all', tier: 'iconic' }, NOW))).toEqual([bi.id]);
    expect(ids(longListRows(all, { character: 'reginald', tier: 'iconic' }, NOW))).toEqual([]);
    const counts = longListCounts(all, 'biscuit', roster, NOW);
    expect(counts.characters).toEqual({ all: 3, biscuit: 2, reginald: 1 });
    expect(counts.tiers).toEqual({ all: 2, iconic: 1, viral_now: 1, rising: 0, gallery: 0 });
  });
});

describe('the Picks view', () => {
  it('opens on the cards unless a deep link or the last choice says the long list', () => {
    expect(picksView('', null)).toBe('cards');
    expect(picksView('', 'list')).toBe('list');
    expect(picksView('', 'garbage')).toBe('cards');
    expect(picksView('view=list', null)).toBe('list');
    expect(picksView('c=biscuit&view=cards', 'list')).toBe('cards');
  });
});
