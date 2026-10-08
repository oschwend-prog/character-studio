// Terminal v3, "Studio at a glance" (spec section 5.1; owner 2026-10-07: "a summary overview with all characters and available
// videos, generated videos, posted ones, views total and per day, month etc"): one row per live character plus All, and the views
// per day by period. Pure functions over the snapshot: v_tracker (the clips), v_queue, v_library, v_channels, v_views_daily
// (migration 0015) and the cadence of studio.settings. Days are London days, counted on the calendar. No browser.
import { clipChip } from './clipstatus';
import { addDays, londonDayKey } from './format';
import { orderRoster } from './roster';
import type { CadenceEntry, Channel, LibraryClip, Snapshot, TrackerRow, ViewsDay } from './types';

/** The name of the row that adds up every live character. */
export const OVERVIEW_ALL = 'All';

const WEEKDAYS = ['mon', 'tue', 'wed', 'thu', 'fri', 'sat', 'sun'];
const DAY_KEY = /^\d{4}-\d{2}-\d{2}$/;

/** Every day from `first` to `last`, both included. */
function dayRange(first: string, last: string): string[] {
  const out: string[] = [];
  for (let d = first; d <= last; d = addDays(d, 1)) out.push(d);
  return out;
}

/**
 * His posts per week: the posting days of his cadence entry, read as the slot functions read them (studio.cadence_days,
 * planning._cadence_days: trimmed, lower-cased, the first 3 letters, each day once); an unknown day is ignored. null when he has
 * no entry or no posting day.
 */
export function postsPerWeek(entry: CadenceEntry | null | undefined): number | null {
  const raw = entry && typeof entry === 'object' ? entry.days : null;
  const list: unknown[] = typeof raw === 'string' ? [raw] : Array.isArray(raw) ? raw : [];
  const days = new Set(list.filter((d): d is string => typeof d === 'string').map((d) => d.trim().toLowerCase().slice(0, 3)));
  const valid = [...days].filter((d) => WEEKDAYS.includes(d)).length;
  return valid || null;
}

/** The character bar of the weekly review (studio.review: not_yet, continue, promote, kill), in the owner's words. */
export type TestStatus = 'not_yet' | 'on_track' | 'promote' | 'at_risk';

export const TEST_STATUS_LABEL: Record<TestStatus, string> = { not_yet: 'Not yet', on_track: 'On track', promote: 'Promote', at_risk: 'At risk' };

/** v_channels.bar_status as a test status: continue is on track, kill is at risk; nothing (no review yet) or anything else is not yet. */
export function testStatusOf(bar: string | null | undefined): TestStatus {
  switch (bar) {
    case 'continue':
      return 'on_track';
    case 'promote':
      return 'promote';
    case 'kill':
      return 'at_risk';
    default:
      return 'not_yet';
  }
}

interface DayValue {
  views: number;
  follows: number;
}

const count = (v: unknown): number => {
  const x = typeof v === 'string' ? Number(v) : v;
  return typeof x === 'number' && Number.isFinite(x) ? x : 0;
};

/**
 * v_views_daily by character and London day, as measured (a day can be negative: a recount correcting an earlier overcount). A day
 * after today (a clock ahead) or a malformed day is left out. The view telescopes (each day is the latest snapshot less the one
 * before), so a window's raw sum is the truth: totals clamp the sum at 0, only the chart clamps each day.
 */
function byDay(rows: ReadonlyArray<ViewsDay>, today: string): Map<string, Map<string, DayValue>> {
  const raw = new Map<string, Map<string, DayValue>>();
  for (const r of rows) {
    const day = typeof r.day === 'string' ? r.day.slice(0, 10) : '';
    if (!r.character_slug || !DAY_KEY.test(day) || day > today) continue;
    const days = raw.get(r.character_slug) ?? new Map<string, DayValue>();
    const v = days.get(day) ?? { views: 0, follows: 0 };
    days.set(day, { views: v.views + count(r.views), follows: v.follows + count(r.follows) });
    raw.set(r.character_slug, days);
  }
  return raw;
}

/** When his next video goes out: a post already booked, else his next slot on the schedule with nothing booked for it. */
export interface NextPost {
  at: string;
  booked: boolean;
}

/** His most viewed video posted in the last 7 days (tap to play: `masterPath`). */
export interface BestVideo {
  clipId: string;
  slug: string;
  hook: string | null;
  views: number;
  postedAt: string;
  masterPath: string | null;
}

export interface OverviewRow {
  /** null = the All row. */
  slug: string | null;
  name: string;
  /** Checked clips filed for him, no Make it yet (the Ready and the Pick a character chips). */
  readyToMake: number;
  /** Of those, the ones whose character the studio chose and that wait for the owner's choice (the Pick a character chip):
   * "6 ready · 2 need your choice". */
  needsYou: number;
  /** Make it tapped, or his clip is being generated, checked or built. */
  beingMade: number;
  /** Finished videos waiting for the owner's OK (the queue). */
  toApprove: number;
  /** Approved or booked videos. */
  scheduled: number;
  posted: number;
  /** The views gained today. Every views and follows total is the window's sum, never below 0: a recount is taken off, so the
   * sum is what his posts show. */
  viewsToday: number;
  /** Today and the 6 days before. */
  views7d: number;
  /** Today and the 29 days before. */
  views30d: number;
  viewsAll: number;
  /** The follows gained today and the 6 days before, never below 0. */
  follows7d: number;
  /** Something was measured for him (v_views_daily has a day): before that the views are zeros and the screen says why. */
  hasViews: boolean;
  nextPost: NextPost | null;
  /** From his cadence; null without one. */
  postsPerWeek: number | null;
  /** Ready clips ÷ his posts per week, to one decimal ("≈ 2 weeks"); null without a cadence. */
  runwayWeeks: number | null;
  /** His Instagram channel's bar; null when he has no Instagram channel (and on the All row). */
  testStatus: TestStatus | null;
  /** Share of his measured clips at 3x or more, weighted by the clips each channel measured; null before any is measured. */
  hitRate: number | null;
  /** His most viewed video posted in the last 7 London days (today and the 6 before), not one still to come. */
  bestThisWeek: BestVideo | null;
}

type OverviewData = Pick<Snapshot, 'characters' | 'tracker' | 'queue' | 'library' | 'channels' | 'viewsDaily' | 'cadence'>;

const READY_CHIPS = new Set(['ready', 'pick']);
const ts = (iso: string | null | undefined) => (iso ? Date.parse(iso) : NaN);
const round1 = (x: number) => Math.round(x * 10) / 10;

/** The hit rate over these channels, weighted by how many clips each one measured; null when none measured a clip. */
function hitRateOf(channels: ReadonlyArray<Pick<Channel, 'hit_rate' | 'measured_clips'>>): number | null {
  let hits = 0;
  let measured = 0;
  for (const ch of channels) {
    const rate = ch.hit_rate == null ? NaN : Number(ch.hit_rate);
    const clips = count(ch.measured_clips);
    if (!Number.isFinite(rate) || clips <= 0) continue;
    hits += rate * clips;
    measured += clips;
  }
  return measured ? hits / measured : null;
}

/** The better of two: more views, then the newer post, then the clip id (stable). */
function better(a: BestVideo | null, b: BestVideo | null): BestVideo | null {
  if (!a || !b) return a ?? b;
  const d = b.views - a.views || ts(b.postedAt) - ts(a.postedAt) || a.clipId.localeCompare(b.clipId);
  return d > 0 ? b : a;
}

function bestOf(library: ReadonlyArray<LibraryClip>, today: string, now: number): BestVideo | null {
  const first = addDays(today, -6);
  let best: BestVideo | null = null;
  for (const c of library) {
    const at = ts(c.posted_at);
    const views = c.views == null ? NaN : Number(c.views);
    if (!Number.isFinite(at) || at > now || londonDayKey(at) < first || !Number.isFinite(views)) continue;
    best = better(best, { clipId: c.id, slug: c.character_slug, hook: c.hook, views, postedAt: c.posted_at!, masterPath: c.master_path });
  }
  return best;
}

/** The sooner of two next posts: a booked one wins over a free slot, then the sooner time. */
function sooner(a: NextPost | null, b: NextPost | null): NextPost | null {
  if (!a || !b) return a ?? b;
  if (a.booked !== b.booked) return a.booked ? a : b;
  return ts(b.at) < ts(a.at) ? b : a;
}

function nextPostOf(library: ReadonlyArray<LibraryClip>, channels: ReadonlyArray<Channel>, now: number): NextPost | null {
  let next: NextPost | null = null;
  for (const c of library) {
    for (const p of c.posts ?? []) {
      if ((p.status === 'scheduled' || p.status === 'posting') && ts(p.scheduled_for) >= now) next = sooner(next, { at: p.scheduled_for, booked: true });
    }
  }
  if (next) return next;
  for (const ch of channels) {
    if (ch.connected && ch.next_slot && ts(ch.next_slot) > now) next = sooner(next, { at: ch.next_slot, booked: false });
  }
  return next;
}

function characterRow(slug: string, name: string, data: OverviewData, days: Map<string, DayValue> | undefined, today: string, now: number): OverviewRow {
  const tracker = data.tracker.filter((r) => r.character_slug === slug);
  const library = data.library.filter((c) => c.character_slug === slug);
  const channels = data.channels.filter((ch) => ch.character_slug === slug);
  const readyToMake = tracker.filter((r: TrackerRow) => r.drop_card && READY_CHIPS.has(clipChip(r))).length;
  // the raw days of the window added up, then never below 0 (days after today were left out by byDay)
  const sum = (from: string, key: keyof DayValue) =>
    Math.max(0, [...(days ?? new Map<string, DayValue>())].reduce((s, [d, v]) => (d >= from ? s + v[key] : s), 0));
  const perWeek = postsPerWeek(data.cadence?.[slug]);
  const instagram = channels.find((ch) => ch.platform === 'instagram');
  return {
    slug,
    name,
    readyToMake,
    needsYou: tracker.filter((r) => r.drop_card && clipChip(r) === 'pick').length,
    beingMade: tracker.filter((r) => clipChip(r) === 'making').length,
    toApprove: data.queue.filter((q) => q.character_slug === slug).length,
    scheduled: library.filter((c) => c.state === 'approved' || c.state === 'scheduled').length,
    posted: library.filter((c) => c.state === 'posted').length,
    viewsToday: sum(today, 'views'),
    views7d: sum(addDays(today, -6), 'views'),
    views30d: sum(addDays(today, -29), 'views'),
    viewsAll: sum('', 'views'),
    follows7d: sum(addDays(today, -6), 'follows'),
    hasViews: Boolean(days?.size),
    nextPost: nextPostOf(library, channels, now),
    postsPerWeek: perWeek,
    runwayWeeks: perWeek ? round1(readyToMake / perWeek) : null,
    testStatus: instagram ? testStatusOf(instagram.bar_status) : null,
    hitRate: hitRateOf(channels),
    bestThisWeek: bestOf(library, today, now),
  };
}

const SUMMED = ['readyToMake', 'needsYou', 'beingMade', 'toApprove', 'scheduled', 'posted', 'viewsToday', 'views7d', 'views30d', 'viewsAll', 'follows7d'] as const;

/**
 * The studio at a glance (spec 5.1): a row per live character in the owner's order, then the All row. All adds up the live rows
 * (counts, views, follows); its next post is the studio's soonest (a booked one first), its runway the ready clips of the
 * characters with a cadence over their posts per week, its hit rate over every live channel, its best video the most viewed of
 * theirs; it has no test status. Views come from v_views_daily: today is the London day of `now`, "7 days" today and the 6 before.
 */
export function overviewRows(data: OverviewData, now: number): OverviewRow[] {
  const today = londonDayKey(now);
  const views = byDay(data.viewsDaily ?? [], today);
  const live = orderRoster(data.characters.filter((c) => c.status === 'live'));
  const rows = live.map((c) => characterRow(c.slug, c.name, data, views.get(c.slug), today, now));
  const paced = rows.filter((r) => r.postsPerWeek != null);
  const perWeek = paced.reduce((s, r) => s + r.postsPerWeek!, 0);
  const all: OverviewRow = {
    slug: null,
    name: OVERVIEW_ALL,
    ...(Object.fromEntries(SUMMED.map((k) => [k, rows.reduce((s, r) => s + r[k], 0)])) as Record<(typeof SUMMED)[number], number>),
    hasViews: rows.some((r) => r.hasViews),
    nextPost: rows.reduce<NextPost | null>((n, r) => sooner(n, r.nextPost), null),
    postsPerWeek: perWeek || null,
    runwayWeeks: perWeek ? round1(paced.reduce((s, r) => s + r.readyToMake, 0) / perWeek) : null,
    testStatus: null,
    hitRate: hitRateOf(data.channels.filter((ch) => live.some((c) => c.slug === ch.character_slug))),
    bestThisWeek: rows.reduce<BestVideo | null>((b, r) => better(b, r.bestThisWeek), null),
  };
  return [...rows, all];
}

// ---- the views per day chart (spec 5.1: 7 days, 30 days, all time) -----------------------------------------------------------------

export type ViewsPeriod = '7d' | '30d' | 'all';

export const VIEWS_PERIODS: ReadonlyArray<{ id: ViewsPeriod; label: string }> = [
  { id: '7d', label: '7 days' },
  { id: '30d', label: '30 days' },
  { id: 'all', label: 'All time' },
];

export interface ViewsSeries {
  /** Every London day of the period, oldest first, today last. */
  days: string[];
  /** One line per character: the views of each day (a day not measured is 0; a recount day below 0 is drawn at 0: the chart only,
   * the totals take it off). */
  lines: { slug: string; views: number[] }[];
  /** Something was measured for these characters (on any day): false = the chart's empty state. */
  hasViews: boolean;
}

/** What the chart says before any views exist (spec 5.1). */
export const VIEWS_EMPTY = 'Views appear here after the first posts are measured (the stats pull runs daily).';

/**
 * The views per day for the chart: every day of the period (7 days or 30 days ending today, or all time from the first day
 * measured), gaps filled with 0. One line per character in `slugs` in that order (a character with no views is a line of zeros),
 * else per character that has views, in the owner's order.
 */
export function viewsSeries(rows: ReadonlyArray<ViewsDay>, period: ViewsPeriod, now: number, slugs?: ReadonlyArray<string>): ViewsSeries {
  const today = londonDayKey(now);
  const views = byDay(rows, today);
  const scope = slugs ? [...new Set(slugs)] : orderRoster([...views.keys()].map((slug) => ({ slug }))).map((c) => c.slug);
  const measured = scope.flatMap((s) => [...(views.get(s)?.keys() ?? [])]).sort();
  const first = period === '7d' ? addDays(today, -6) : period === '30d' ? addDays(today, -29) : measured[0] ?? today;
  const days = dayRange(first, today);
  return {
    days,
    lines: scope.map((slug) => ({ slug, views: days.map((d) => Math.max(0, views.get(slug)?.get(d)?.views ?? 0)) })),
    hasViews: measured.length > 0,
  };
}
