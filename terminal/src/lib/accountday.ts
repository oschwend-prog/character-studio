// "Account per day" (owner 2026-10-15): what Instagram and Postiz say the ACCOUNT got each day (Stories included) beside what his
// Reels gained, over the last 7 London days, so the difference (Stories, older posts) is visible. Postiz and Instagram give no
// numbers for a single Story, only the account's daily totals, which `studio metrics accounts` stores every 6 hours as runs of kind
// `account_daily` (one row per London day: details {day, accounts: {handle: {views, reach, ..., replies}}}). The Reels figure is
// the existing v_views_daily (what his posts gained between our readings, counted on the day we read them). Pure functions, no browser.
import { addDays, londonDate, londonDayKey } from './format';
import type { ViewsDay } from './types';

export const ACCOUNT_DAYS_SHOWN = 7;

/** The numbers the metrics job stores per account and day; a number Postiz did not report is absent, never 0. */
export type AccountNumbers = Partial<Record<'views' | 'reach' | 'likes' | 'comments' | 'shares' | 'saves' | 'replies', number>>;

const FIELDS = ['views', 'reach', 'likes', 'comments', 'shares', 'saves', 'replies'] as const;

/** One London day of the stored totals: every account that was read, by handle. */
export interface AccountDay {
  /** The London day, YYYY-MM-DD. */
  day: string;
  accounts: Record<string, AccountNumbers>;
}

const isCount = (v: unknown): v is number => typeof v === 'number' && Number.isFinite(v) && v >= 0;
const isDay = (v: unknown): v is string => typeof v === 'string' && /^\d{4}-\d{2}-\d{2}$/.test(v) && !Number.isNaN(Date.parse(`${v}T12:00:00Z`));

/**
 * The days in the `account_daily` runs (`details.day`, `details.accounts`), oldest first. A run with no usable day or no account with a
 * number is skipped; a field that is not a plain count (a string, a negative, NaN) is left out. Two runs of one day join, the later
 * one in the list winning per handle (the job keeps one row per day; this only keeps a stray second row harmless).
 */
export function parseAccountDays(rows: ReadonlyArray<{ details?: unknown } | null | undefined>): AccountDay[] {
  const byDay = new Map<string, Record<string, AccountNumbers>>();
  for (const r of rows) {
    const d = r?.details;
    if (!d || typeof d !== 'object') continue;
    const { day, accounts } = d as { day?: unknown; accounts?: unknown };
    if (!isDay(day) || !accounts || typeof accounts !== 'object' || Array.isArray(accounts)) continue;
    const mine: Record<string, AccountNumbers> = {};
    for (const [handle, raw] of Object.entries(accounts as Record<string, unknown>)) {
      if (!raw || typeof raw !== 'object') continue;
      const nums: AccountNumbers = {};
      for (const f of FIELDS) {
        const v = (raw as Record<string, unknown>)[f];
        if (isCount(v)) nums[f] = v;
      }
      if (Object.keys(nums).length) mine[handle] = nums;
    }
    if (Object.keys(mine).length === 0) continue;
    byDay.set(day, { ...(byDay.get(day) ?? {}), ...mine });
  }
  return [...byDay.keys()].sort().map((day) => ({ day, accounts: byDay.get(day)! }));
}

/** A handle without case, spaces or the @: how the stored handle is matched to the character's own. */
export const handleKey = (h: string): string => h.trim().replace(/^@/, '').toLowerCase();

/** The numbers of a line (one day, or the week). `null` = nothing known, never 0. */
export interface AccountLine {
  /** The account's views that day (all his accounts that were read, added up). */
  views: number | null;
  reach: number | null;
  replies: number | null;
  /** The views his Reels gained that day (v_views_daily), null when nobody measured them that day. */
  reels: number | null;
  /** What is left of the account's views after the Reels, never below 0: Stories and older posts. null without the account's views. */
  rest: number | null;
}

export interface AccountPerDayRow extends AccountLine {
  day: string;
  /** "Today", else "Tue 13 Oct". */
  label: string;
  today: boolean;
}

export interface AccountPerDayModel {
  /** The last 7 London days, oldest first, today last. */
  rows: AccountPerDayRow[];
  total: AccountLine;
  /** The account views per row, for the sparkline (null = no reading that day). */
  views: (number | null)[];
  /** His accounts (as he spells them) that have a reading in these 7 days: what the numbers add up. */
  counted: string[];
  /** Any reading of views, reach or replies in the week. */
  hasData: boolean;
}

const sum = (xs: ReadonlyArray<number | null>): number | null => {
  const got = xs.filter((x): x is number => x != null);
  return got.length ? got.reduce((a, b) => a + b, 0) : null;
};

/**
 * The week for one character: per London day (the last 7, today last) his accounts' views, reach and replies added up over the
 * accounts of `handles` that were read that day, the views his Reels gained (`viewsDaily`, his rows only, a negative recount read as
 * 0) and Rest = the account's views minus the Reels, never below 0 (the Stories, older posts and what the readings did not catch).
 * A day with no reading has `null`s. The totals add each column over the week (Rest adds the days' rests).
 */
export function accountPerDay(
  slug: string,
  handles: ReadonlyArray<string | null | undefined>,
  days: ReadonlyArray<AccountDay>,
  viewsDaily: ReadonlyArray<ViewsDay>,
  now: number,
): AccountPerDayModel {
  const today = londonDayKey(now);
  const keys = Array.from({ length: ACCOUNT_DAYS_SHOWN }, (_, i) => addDays(today, i - (ACCOUNT_DAYS_SHOWN - 1)));
  const mine = new Map<string, string>(); // handle key -> the handle as he spells it
  for (const h of handles) if (h && handleKey(h) && !mine.has(handleKey(h))) mine.set(handleKey(h), h);
  const stored = new Map(days.map((d) => [d.day, d.accounts]));
  const seen = new Set<string>();
  const reelsOf = (day: string): number | null => {
    const hit = viewsDaily.filter((v) => v.character_slug === slug && String(v.day).slice(0, 10) === day);
    return hit.length ? hit.reduce((s, v) => s + Math.max(0, Number(v.views) || 0), 0) : null;
  };

  const rows: AccountPerDayRow[] = keys.map((day) => {
    const read: AccountNumbers[] = [];
    for (const [handle, nums] of Object.entries(stored.get(day) ?? {})) {
      const k = handleKey(handle);
      if (mine.has(k)) {
        read.push(nums);
        seen.add(k);
      }
    }
    const views = sum(read.map((n) => n.views ?? null));
    const reels = reelsOf(day);
    return {
      day,
      label: day === today ? 'Today' : londonDate(Date.parse(`${day}T12:00:00Z`)),
      today: day === today,
      views,
      reach: sum(read.map((n) => n.reach ?? null)),
      replies: sum(read.map((n) => n.replies ?? null)),
      reels,
      rest: views == null ? null : Math.max(0, views - (reels ?? 0)),
    };
  });
  const col = (f: keyof AccountLine) => sum(rows.map((r) => r[f]));
  return {
    rows,
    total: { views: col('views'), reach: col('reach'), replies: col('replies'), reels: col('reels'), rest: col('rest') },
    views: rows.map((r) => r.views),
    counted: [...mine].filter(([k]) => seen.has(k)).map(([, h]) => h),
    hasData: rows.some((r) => r.views != null || r.reach != null || r.replies != null),
  };
}

export interface SparkGeometry {
  /** One `points` string per run of days with a number (a day without one breaks the line); a single day is one point. */
  segments: string[];
  /** The newest day with a number, where the end marker goes; null without any. */
  last: { x: number; y: number } | null;
  /** The biggest value: the top of the scale (0 at the bottom). */
  max: number;
}

const r1 = (x: number) => Math.round(x * 10) / 10;

/**
 * The sparkline of `values` (one per day, null = no reading) in a `w` x `h` pixel box with `pad` pixels round it, so a stroke and
 * the end marker never leave the box: the first day at the left edge, the last at the right, 0 at the bottom and the biggest value
 * at the top. Fixed pixels (not stretched), so the marker stays round.
 */
export function sparkSegments(values: ReadonlyArray<number | null>, w: number, h: number, pad: number): SparkGeometry {
  const peak = Math.max(0, ...values.filter((v): v is number => v != null));
  const n = values.length;
  const x = (i: number) => (n <= 1 ? pad : pad + (i * (w - 2 * pad)) / (n - 1));
  const y = (v: number) => (peak <= 0 ? h - pad : h - pad - (Math.max(0, v) / peak) * (h - 2 * pad));
  const segments: string[] = [];
  let run: string[] = [];
  let last: SparkGeometry['last'] = null;
  const flush = () => {
    if (run.length) segments.push(run.join(' '));
    run = [];
  };
  values.forEach((v, i) => {
    if (v == null) return flush();
    run.push(`${r1(x(i))},${r1(y(v))}`);
    last = { x: r1(x(i)), y: r1(y(v)) };
    if (i + 1 < n && values[i + 1] == null) flush();
  });
  flush();
  return { segments, last, max: peak };
}
