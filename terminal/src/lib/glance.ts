// Terminal v3, Today's "Studio at a glance" in words (spec 5.1; owner 2026-10-07: "a summary overview with all characters and
// available videos, generated videos, posted ones, views total and per day, month etc"). overview.ts counts; this file only says
// the numbers in the owner's words and shapes the views chart. Pure functions, no browser.
import { addDays, londonDate, londonDayKey, londonTime } from './format';
import { TEST_STATUS_LABEL, type NextPost, type TestStatus, type ViewsSeries } from './overview';
import type { QueueClip, ViewsDay } from './types';

/**
 * Runway (ready clips ÷ his posts per week) in words: "≈ 2 weeks", "≈ 1 week", "under a week", "nothing ready"; "—" without a
 * cadence (null) or a number that is not one.
 */
export function runwayLabel(weeks: number | null | undefined): string {
  if (weeks == null || !Number.isFinite(weeks)) return '—';
  if (weeks <= 0) return 'nothing ready';
  if (weeks < 1) return 'under a week';
  const n = Math.round(weeks);
  return `≈ ${n} week${n === 1 ? '' : 's'}`;
}

/** His test status in words (not yet, on track, promote, at risk); "—" when he has no Instagram channel (and on the All row). */
export function testStatusLabel(s: TestStatus | null | undefined): string {
  return s ? TEST_STATUS_LABEL[s] : '—';
}

/** The tag look of a test status: on track ice, promote the lit ice, at risk red, not yet quiet. */
export const TEST_STATUS_TONE: Record<TestStatus, 'quiet' | 'live' | 'hit' | 'alert'> = {
  not_yet: 'quiet',
  on_track: 'live',
  promote: 'hit',
  at_risk: 'alert',
};

/** His hit rate (a share, 0-1) as "33%"; "—" before anything is measured. */
export function hitsLabel(rate: number | null | undefined): string {
  return rate == null || !Number.isFinite(rate) ? '—' : `${Math.round(Math.min(1, Math.max(0, rate)) * 100)}%`;
}

/**
 * When his next video goes out, in London time: "Today 19:30", "Tomorrow 12:30", else "Mon 12 Oct 19:00"; the note says whether a
 * video is booked for it or nothing is booked yet. No slot at all: "—", "no slot yet".
 */
export function nextPostLabel(next: NextPost | null | undefined, now: number): { when: string; note: string } {
  const at = next ? Date.parse(next.at) : NaN;
  if (!next || !Number.isFinite(at)) return { when: '—', note: 'no slot yet' };
  const today = londonDayKey(now);
  const day = londonDayKey(at);
  const word = day === today ? 'Today' : day === addDays(today, 1) ? 'Tomorrow' : londonDate(at);
  return { when: `${word} ${londonTime(at)}`, note: next.booked ? 'booked' : 'nothing booked yet' };
}

const count = (v: unknown): number => {
  const x = typeof v === 'string' ? Number(v) : v;
  return typeof x === 'number' && Number.isFinite(x) ? x : 0;
};

/**
 * The views of the week before this one (the 7 London days before "7 days": today-13 to today-7), for the comparison next to
 * the 7 days figure. Per character the raw days added up and never below 0, as overview.ts does for its windows; several
 * characters (the All row) add up their own. A day after today or a malformed day is left out.
 */
export function lastWeekViews(rows: ReadonlyArray<ViewsDay>, slugs: ReadonlyArray<string>, now: number): number {
  const today = londonDayKey(now);
  const [from, to] = [addDays(today, -13), addDays(today, -7)];
  return [...new Set(slugs)].reduce((total, slug) => {
    const raw = rows.reduce((s, r) => {
      const day = typeof r.day === 'string' ? r.day.slice(0, 10) : '';
      return r.character_slug === slug && day >= from && day <= to ? s + count(r.views) : s;
    }, 0);
    return total + Math.max(0, raw);
  }, 0);
}

/** The finished videos waiting for his OK, the newest first (Approve these, spec 5.3); a bad time sorts last. */
export function approvalOrder<Q extends Pick<QueueClip, 'id' | 'created_at'>>(queue: ReadonlyArray<Q>): Q[] {
  const at = (q: Q) => {
    const t = Date.parse(q.created_at);
    return Number.isFinite(t) ? t : Number.NEGATIVE_INFINITY;
  };
  return [...queue].sort((a, b) => (at(a) === at(b) ? a.id.localeCompare(b.id) : at(b) > at(a) ? 1 : -1));
}

// ---- the views per day chart ------------------------------------------------------------------------------------------------------

/** The line colour of a character (the Budget page's series colours); a character without one is drawn in the second ink. */
export function seriesColor(slug: string): string {
  return ['franz', 'reginald', 'lenny', 'biscuit'].includes(slug) ? `var(--series-${slug})` : 'var(--ink-2)';
}

/** The smallest round number (1, 2 or 5 times a power of ten) at or above `n`; 1 for nothing (an empty chart still has a scale). */
export function niceCeil(n: number): number {
  if (!Number.isFinite(n) || n <= 1) return 1;
  const power = 10 ** Math.floor(Math.log10(n));
  const step = [1, 2, 5, 10].find((m) => m * power >= n) ?? 10;
  return step * power;
}

export interface ChartGeometry {
  /** The top of the scale: the highest day of any line, rounded up to a round number. */
  max: number;
  /** One polyline per character in a 0-100 box (y grows downward), the order of the series. */
  lines: { slug: string; points: string; total: number }[];
}

const r1 = (x: number) => Math.round(x * 10) / 10;

/**
 * The chart's lines in a 100 x 100 box (the SVG stretches it to its frame, its strokes keep their width): the first day at x 0,
 * today at x 100, a single day drawn across the whole width; views 0 at the bottom (y 98) and the scale's top at y 2, so a
 * stroke never leaves the box. `total` is the period's views of that line (what the legend says).
 */
export function chartGeometry(series: Pick<ViewsSeries, 'days' | 'lines'>): ChartGeometry {
  const peak = Math.max(0, ...series.lines.flatMap((l) => l.views));
  const max = niceCeil(peak);
  const n = series.days.length;
  const x = (i: number) => (n <= 1 ? 0 : (i * 100) / (n - 1));
  const y = (v: number) => 98 - (Math.max(0, v) / max) * 96;
  return {
    max,
    lines: series.lines.map((l) => {
      const pts = l.views.map((v, i) => `${r1(x(i))},${r1(y(v))}`);
      if (n === 1 && pts.length === 1) pts.push(`100,${r1(y(l.views[0]))}`);
      return { slug: l.slug, points: pts.join(' '), total: l.views.reduce((s, v) => s + Math.max(0, v), 0) };
    }),
  };
}
