// "Account per day" (owner 2026-10-15): what Instagram and Postiz say the ACCOUNT got (Stories included) beside what his Reels gained,
// over the last 7 London days, so the difference (Stories, older posts) is visible. Postiz and Instagram give no numbers for a single
// Story, only the account's figures, which `studio metrics accounts` stores every 6 hours as runs of kind `account_daily` (one row per
// London day). Verified live 2026-10-15: only REACH is per day (details {day, accounts: {handle: {reach}}}); views, likes, comments,
// shares, saves and replies are Instagram's ONE total over the last 7 days, kept on the row of the day it was read (details.window =
// {days: 7, read_at, accounts: {handle: {views, likes, ...}}}). So the table shows reach per day beside the Reels, and the account's
// views are one 7-day figure. The Reels figure is the existing v_views_daily (what his posts gained between our readings, counted on
// the day we read them). Pure functions, no browser.
import { addDays, formatAge, londonDate, londonDayKey } from './format';
import type { ViewsDay } from './types';

export const ACCOUNT_DAYS_SHOWN = 7;

/** The numbers the metrics job stores per account: per day (in practice reach only) or in the window; a number Postiz did not report is
 * absent, never 0. */
export type AccountNumbers = Partial<Record<'views' | 'reach' | 'likes' | 'comments' | 'shares' | 'saves' | 'replies', number>>;

const FIELDS = ['views', 'reach', 'likes', 'comments', 'shares', 'saves', 'replies'] as const;

/** Instagram's totals over the last `days` days, read at `readAt`: one number per account, not per day. */
export interface AccountWindow {
  /** How many days the totals cover (7). */
  days: number;
  /** When the metrics job read it (epoch ms); null when the stored time is unusable. */
  readAt: number | null;
  accounts: Record<string, AccountNumbers>;
}

/** One London day of the stored figures: the daily numbers of every account that was read, and the window read on that day (if any). */
export interface AccountDay {
  /** The London day, YYYY-MM-DD. */
  day: string;
  /** The per-day numbers by handle (reach); empty on a row that only holds the window. */
  accounts: Record<string, AccountNumbers>;
  window?: AccountWindow;
}

const isCount = (v: unknown): v is number => typeof v === 'number' && Number.isFinite(v) && v >= 0;
const isDay = (v: unknown): v is string => typeof v === 'string' && /^\d{4}-\d{2}-\d{2}$/.test(v) && !Number.isNaN(Date.parse(`${v}T12:00:00Z`));

const later = (a: number | null, b: number | null): number | null => (a == null ? b : b == null ? a : Math.max(a, b));

/** The accounts of a stored `accounts` object, keeping the handles that have a number and only the numbers it knows. */
function readAccounts(raw: unknown): Record<string, AccountNumbers> {
  const out: Record<string, AccountNumbers> = {};
  if (!raw || typeof raw !== 'object' || Array.isArray(raw)) return out;
  for (const [handle, one] of Object.entries(raw as Record<string, unknown>)) {
    if (!one || typeof one !== 'object') continue;
    const nums: AccountNumbers = {};
    for (const f of FIELDS) {
      const v = (one as Record<string, unknown>)[f];
      if (isCount(v)) nums[f] = v;
    }
    if (Object.keys(nums).length) out[handle] = nums;
  }
  return out;
}

/** A stored `window` ({days, read_at, accounts}), or undefined when it holds no account with a number. */
function readWindow(raw: unknown): AccountWindow | undefined {
  if (!raw || typeof raw !== 'object' || Array.isArray(raw)) return undefined;
  const { days, read_at, accounts } = raw as { days?: unknown; read_at?: unknown; accounts?: unknown };
  const mine = readAccounts(accounts);
  if (Object.keys(mine).length === 0) return undefined;
  const at = typeof read_at === 'string' ? Date.parse(read_at) : NaN;
  return {
    days: typeof days === 'number' && Number.isInteger(days) && days > 0 ? days : ACCOUNT_DAYS_SHOWN,
    readAt: Number.isFinite(at) ? at : null,
    accounts: mine,
  };
}

/**
 * The days in the `account_daily` runs (`details.day`, `details.accounts`, `details.window`), oldest first. A run with no usable day, or
 * with neither an account with a number nor a window, is skipped; a field that is not a plain count (a string, a negative, NaN) is left
 * out. Two runs of one day join, the later one in the list winning per handle (the job keeps one row per day; this only keeps a stray
 * second row harmless).
 */
export function parseAccountDays(rows: ReadonlyArray<{ details?: unknown } | null | undefined>): AccountDay[] {
  const byDay = new Map<string, { accounts: Record<string, AccountNumbers>; window?: AccountWindow }>();
  for (const r of rows) {
    const d = r?.details;
    if (!d || typeof d !== 'object') continue;
    const { day, accounts, window } = d as { day?: unknown; accounts?: unknown; window?: unknown };
    if (!isDay(day)) continue;
    const mine = readAccounts(accounts);
    const win = readWindow(window);
    if (Object.keys(mine).length === 0 && !win) continue;
    const held = byDay.get(day);
    const joined: AccountWindow | undefined =
      held?.window && win
        ? { days: win.days, readAt: later(held.window.readAt, win.readAt), accounts: { ...held.window.accounts, ...win.accounts } }
        : (win ?? held?.window);
    byDay.set(day, { accounts: { ...(held?.accounts ?? {}), ...mine }, ...(joined ? { window: joined } : {}) });
  }
  return [...byDay.keys()].sort().map((day) => ({ day, ...byDay.get(day)! }));
}

/** A handle without case, spaces or the @: how the stored handle is matched to the character's own. */
export const handleKey = (h: string): string => h.trim().replace(/^@/, '').toLowerCase();

/** One day's line of the table: the account's reach that day, and the views his Reels gained. `null` = nothing known, never 0. */
export interface AccountLine {
  /** The account's reach that day (all his accounts that were read, added up). */
  reach: number | null;
  /** The views his Reels gained that day (v_views_daily), null when nobody measured them that day. */
  reels: number | null;
}

export interface AccountPerDayRow extends AccountLine {
  day: string;
  /** "Today", else "Tue 13 Oct". */
  label: string;
  today: boolean;
}

/** The newest 7-day window read for his accounts: Instagram's totals (Stories included) over the last `days` days. */
export interface AccountWindowModel {
  /** The window's views, likes, comments and replies added up over his accounts that were read; null when none reported it. */
  views: number | null;
  likes: number | null;
  comments: number | null;
  replies: number | null;
  /** How many days it covers (7). */
  days: number;
  /** When it was read (epoch ms), null when unknown. */
  readAt: number | null;
  /** "2h ago"; null when the read time is unknown. */
  readAgo: string | null;
  /** Views his Reels gained over the last 7 London days (null when nobody measured them). */
  reels: number | null;
  /** The window's views minus the Reels' gained views: Stories and older posts. null unless both are known and it is not below 0. */
  rest: number | null;
}

export interface AccountPerDayModel {
  /** The last 7 London days, oldest first, today last. */
  rows: AccountPerDayRow[];
  /** The views his Reels gained over those 7 days (the sum of the rows), null when nobody measured them. */
  reelsWeek: number | null;
  /** The account's reach per row, for the sparkline (null = no reading that day). */
  reach: (number | null)[];
  /** The newest window of his accounts, null before the first one. */
  window: AccountWindowModel | null;
  /** His accounts (as he spells them) that have a reading in these 7 days or in the window: what the numbers add up. */
  counted: string[];
  /** Any reach in the week, or a window. */
  hasData: boolean;
}

const sum = (xs: ReadonlyArray<number | null>): number | null => {
  const got = xs.filter((x): x is number => x != null);
  return got.length ? got.reduce((a, b) => a + b, 0) : null;
};

/**
 * The week for one character. Per London day (the last 7, today last): the reach of his accounts added up over the accounts of
 * `handles` that were read that day, and the views his Reels gained (`viewsDaily`, his rows only, a negative recount read as 0). Reach
 * is the only figure Instagram gives per day. The account's views are one number: the newest window (`AccountDay.window`) of his
 * accounts, summed over his handles (also likes, comments, replies), with when it was read and, beside it, what his Reels gained over
 * the same 7 London days and the rest = window views minus those Reels (Stories, older posts), only when both are known and the rest is
 * not below 0. A day with no reading has `null`s.
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
        if (nums.reach != null) seen.add(k);
      }
    }
    return {
      day,
      label: day === today ? 'Today' : londonDate(Date.parse(`${day}T12:00:00Z`)),
      today: day === today,
      reach: sum(read.map((n) => n.reach ?? null)),
      reels: reelsOf(day),
    };
  });
  const reelsWeek = sum(rows.map((r) => r.reels));

  // The newest window that one of his accounts was read in (rows newest day first; a day's row holds the last read of that day).
  let window: AccountWindowModel | null = null;
  for (const d of [...days].sort((a, b) => b.day.localeCompare(a.day))) {
    if (!d.window) continue;
    const read: AccountNumbers[] = [];
    for (const [handle, nums] of Object.entries(d.window.accounts)) {
      const k = handleKey(handle);
      if (mine.has(k)) {
        read.push(nums);
        seen.add(k);
      }
    }
    if (read.length === 0) continue;
    const views = sum(read.map((n) => n.views ?? null));
    const rest = views != null && reelsWeek != null && views - reelsWeek >= 0 ? views - reelsWeek : null;
    window = {
      views,
      likes: sum(read.map((n) => n.likes ?? null)),
      comments: sum(read.map((n) => n.comments ?? null)),
      replies: sum(read.map((n) => n.replies ?? null)),
      days: d.window.days,
      readAt: d.window.readAt,
      readAgo: d.window.readAt == null ? null : formatAge(d.window.readAt, now),
      reels: reelsWeek,
      rest,
    };
    break;
  }
  return {
    rows,
    reelsWeek,
    reach: rows.map((r) => r.reach),
    window,
    counted: [...mine].filter(([k]) => seen.has(k)).map(([, h]) => h),
    hasData: window != null || rows.some((r) => r.reach != null),
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
