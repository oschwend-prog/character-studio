// Today's "Studio at a glance" in words and the views chart's shape (spec 5.1).
import { describe, expect, it } from 'vitest';
import {
  TEST_STATUS_TONE, approvalOrder, chartGeometry, hitsLabel, lastWeekViews, nextPostLabel, niceCeil, runwayLabel, seriesColor,
  testStatusLabel,
} from './glance';
import type { ViewsDay } from './types';

// Thursday 8 October 2026, noon in London (BST)
const NOW = Date.parse('2026-10-08T12:00:00+01:00');
const views = (slug: string, day: string, v: number | string): ViewsDay => ({ character_slug: slug, day, views: v as number, follows: 0 });

describe('runwayLabel', () => {
  it('says the weeks his ready clips last, rounded, in words', () => {
    expect(runwayLabel(2)).toBe('≈ 2 weeks');
    expect(runwayLabel(1.4)).toBe('≈ 1 week');
    expect(runwayLabel(1.5)).toBe('≈ 2 weeks');
    expect(runwayLabel(0.7)).toBe('under a week');
    expect(runwayLabel(0)).toBe('nothing ready');
  });
  it('is a dash without a cadence or with a number that is not one', () => {
    expect(runwayLabel(null)).toBe('—');
    expect(runwayLabel(undefined)).toBe('—');
    expect(runwayLabel(Number.NaN)).toBe('—');
    expect(runwayLabel(Number.POSITIVE_INFINITY)).toBe('—');
  });
});

describe('test status and hits in words', () => {
  it('names the four statuses as the owner says them, a dash without an Instagram channel', () => {
    expect(testStatusLabel('not_yet')).toBe('Not yet');
    expect(testStatusLabel('on_track')).toBe('On track');
    expect(testStatusLabel('promote')).toBe('Promote');
    expect(testStatusLabel('at_risk')).toBe('At risk');
    expect(testStatusLabel(null)).toBe('—');
    expect(TEST_STATUS_TONE.at_risk).toBe('alert');
    expect(TEST_STATUS_TONE.not_yet).toBe('quiet');
  });
  it('shows the hit rate as a whole percentage, a dash before anything is measured', () => {
    expect(hitsLabel(1 / 3)).toBe('33%');
    expect(hitsLabel(0)).toBe('0%');
    expect(hitsLabel(1)).toBe('100%');
    expect(hitsLabel(null)).toBe('—');
    expect(hitsLabel(Number.NaN)).toBe('—');
  });
});

describe('nextPostLabel', () => {
  it('says today, tomorrow or the date, in London time, and whether a video is booked', () => {
    expect(nextPostLabel({ at: '2026-10-08T18:30:00Z', booked: true }, NOW)).toEqual({ when: 'Today 19:30', note: 'booked' });
    expect(nextPostLabel({ at: '2026-10-09T11:30:00Z', booked: false }, NOW)).toEqual({ when: 'Tomorrow 12:30', note: 'nothing booked yet' });
    expect(nextPostLabel({ at: '2026-10-12T18:00:00Z', booked: true }, NOW)).toEqual({ when: 'Mon 12 Oct 19:00', note: 'booked' });
  });
  it('counts London days: 23:30 UTC on the 8th is already Friday in London', () => {
    expect(nextPostLabel({ at: '2026-10-08T23:30:00Z', booked: true }, NOW).when).toBe('Tomorrow 00:30');
  });
  it('is a dash with no slot or a time that is not one', () => {
    expect(nextPostLabel(null, NOW)).toEqual({ when: '—', note: 'no slot yet' });
    expect(nextPostLabel({ at: 'soon', booked: true }, NOW)).toEqual({ when: '—', note: 'no slot yet' });
  });
});

describe('lastWeekViews', () => {
  const rows = [
    views('franz', '2026-10-08', 50), // today: this week
    views('franz', '2026-10-02', 40), // today-6: this week
    views('franz', '2026-10-01', 30), // today-7: last week
    views('franz', '2026-09-25', 20), // today-13: last week
    views('franz', '2026-09-24', 999), // today-14: before
    views('lenny', '2026-09-28', '15'), // a bigint as a string
    views('lenny', '2026-09-29', -40), // a recount: Lenny's week sums below 0, shown 0
    views('reginald', '2026-09-30', 7),
  ];
  it('adds up the 7 days before this week (today-13 to today-7)', () => {
    expect(lastWeekViews(rows, ['franz'], NOW)).toBe(50);
    expect(lastWeekViews(rows, ['reginald'], NOW)).toBe(7);
  });
  it('never goes below 0 for one character, and the All row adds up each character once', () => {
    expect(lastWeekViews(rows, ['lenny'], NOW)).toBe(0);
    expect(lastWeekViews(rows, ['franz', 'lenny', 'reginald', 'franz'], NOW)).toBe(57);
    expect(lastWeekViews([], ['franz'], NOW)).toBe(0);
  });
});

describe('approvalOrder', () => {
  it('lists the newest finished video first, a bad time last', () => {
    const q = [
      { id: 'a', created_at: '2026-10-07T10:00:00Z' },
      { id: 'b', created_at: 'not a time' },
      { id: 'c', created_at: '2026-10-08T09:00:00Z' },
      { id: 'd', created_at: '2026-10-06T10:00:00Z' },
    ];
    expect(approvalOrder(q).map((x) => x.id)).toEqual(['c', 'a', 'd', 'b']);
    expect(q.map((x) => x.id)).toEqual(['a', 'b', 'c', 'd']); // a new list
  });
});

describe('the views chart', () => {
  it('rounds the scale up to 1, 2 or 5 times a power of ten', () => {
    expect(niceCeil(0)).toBe(1);
    expect(niceCeil(1)).toBe(1);
    expect(niceCeil(7)).toBe(10);
    expect(niceCeil(12)).toBe(20);
    expect(niceCeil(180)).toBe(200);
    expect(niceCeil(201)).toBe(500);
    expect(niceCeil(5000)).toBe(5000);
    expect(niceCeil(Number.NaN)).toBe(1);
  });

  it('spreads the days across the width and puts views on a scale from the bottom', () => {
    const g = chartGeometry({
      days: ['2026-10-06', '2026-10-07', '2026-10-08'],
      lines: [
        { slug: 'reginald', views: [0, 100, 200] },
        { slug: 'lenny', views: [50, 0, 25] },
      ],
    });
    expect(g.max).toBe(200);
    expect(g.lines[0]).toEqual({ slug: 'reginald', points: '0,98 50,50 100,2', total: 300 });
    expect(g.lines[1].points).toBe('0,74 50,98 100,86');
    expect(g.lines[1].total).toBe(75);
  });

  it('draws a single day across the whole width and an all-zero chart flat on the bottom', () => {
    expect(chartGeometry({ days: ['2026-10-08'], lines: [{ slug: 'franz', views: [3] }] }).lines[0].points).toBe('0,40.4 100,40.4');
    const flat = chartGeometry({ days: ['2026-10-07', '2026-10-08'], lines: [{ slug: 'franz', views: [0, 0] }] });
    expect(flat.max).toBe(1);
    expect(flat.lines[0].points).toBe('0,98 100,98');
  });

  it('never draws below the bottom, and has no NaN with no line at all', () => {
    const g = chartGeometry({ days: ['2026-10-07', '2026-10-08'], lines: [{ slug: 'franz', views: [-5, 10] }] });
    expect(g.lines[0].points).toBe('0,98 100,2');
    expect(g.lines[0].total).toBe(10);
    expect(chartGeometry({ days: [], lines: [] })).toEqual({ max: 1, lines: [] });
  });

  it('gives each character his series colour, the second ink otherwise', () => {
    expect(seriesColor('reginald')).toBe('var(--series-reginald)');
    expect(seriesColor('borat-type')).toBe('var(--ink-2)');
  });
});
