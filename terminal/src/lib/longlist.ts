// The long list: every proposed pick (v_picks, status new) in one sortable table, so the owner can see which clips should post
// first. Pure functions, no browser: the row model (what each column shows and sorts by), compact numbers, the age, the default
// order, the header-tap sort and the filters.
import { ageDays, pickVelocity } from './analyst';
import { CREDITS, TIERS, estimateCredits, tierOf } from './rules';
import type { OwnerMode, Pick as ViralPick, Tier } from './types';

export type LongListKey =
  | 'clip' | 'character' | 'tier' | 'rec' | 'views' | 'age' | 'velocity' | 'outlier' | 'sat' | 'fit' | 'feas' | 'mode' | 'credits' | 'score';
export type SortDir = 'asc' | 'desc';
/** `default` = the tier order (iconic first, inside it the most recognisable), then the score. */
export interface LongListSort {
  key: LongListKey | 'default';
  dir: SortDir;
}
export const DEFAULT_SORT: LongListSort = { key: 'default', dir: 'asc' };

/** The sortable columns, left to right after the picture, with the direction a first tap sorts in. */
export const LONG_LIST_COLUMNS: ReadonlyArray<{ key: LongListKey; label: string; title: string; first: SortDir; numeric: boolean }> = [
  { key: 'clip', label: 'Clip', title: 'What the video is (the concept)', first: 'asc', numeric: false },
  { key: 'character', label: 'Who', title: 'The character who makes it', first: 'asc', numeric: false },
  { key: 'tier', label: 'Tier', title: 'Category: Broke the internet first', first: 'asc', numeric: false },
  { key: 'rec', label: 'Rec', title: 'Recognisability 0-10 (iconic moments only)', first: 'desc', numeric: true },
  { key: 'views', label: 'Views', title: 'Views (an iconic moment: its original video’s views)', first: 'desc', numeric: true },
  { key: 'age', label: 'Age', title: 'How old the video is (iconic: years, else days)', first: 'asc', numeric: true },
  { key: 'velocity', label: 'Views/day', title: 'Views per day since it was posted', first: 'desc', numeric: true },
  { key: 'outlier', label: 'Outlier', title: 'Views against the creator’s own median', first: 'desc', numeric: true },
  { key: 'sat', label: 'Sat', title: 'Similar videos found this week (fewer is fresher)', first: 'asc', numeric: true },
  { key: 'fit', label: 'Fit', title: 'Fit with the character, 0-10', first: 'desc', numeric: true },
  { key: 'feas', label: 'Feas', title: 'How easy for our pipeline, 0-10', first: 'desc', numeric: true },
  { key: 'mode', label: 'Mode', title: 'Drop-in or Recreate', first: 'asc', numeric: false },
  { key: 'credits', label: 'Cr', title: 'Higgsfield credits it should cost', first: 'asc', numeric: true },
  { key: 'score', label: 'Score', title: 'Total score of 100', first: 'desc', numeric: true },
];

const YEAR_DAYS = 365.25;
const finite = (v: unknown): number | null => (typeof v === 'number' && Number.isFinite(v) ? v : null);

/**
 * A count the way the long list prints it: 6,083,137,818 -> "6.08B", 2,700,000 -> "2.7M", 731,700 -> "731.7K", 950 -> "950".
 * Billions keep two decimals, millions and thousands one, trailing zeros dropped; a value that rounds up to the next unit moves
 * to it (999,960 -> "1M"). Null or not a number -> an em dash.
 */
export function compactCount(n: number | null | undefined): string {
  const v = finite(n);
  if (v == null) return '—';
  const sign = v < 0 ? '-' : '';
  const a = Math.abs(v);
  const units: Array<[number, string, number]> = [[1e9, 'B', 2], [1e6, 'M', 1], [1e3, 'K', 1]];
  for (let i = 0; i < units.length; i++) {
    const [size, suffix, digits] = units[i];
    if (a < size) continue;
    const scaled = Number((a / size).toFixed(digits));
    if (scaled >= 1000 && i > 0) {
      const [up, upSuffix, upDigits] = units[i - 1];
      return `${sign}${Number((a / up).toFixed(upDigits))}${upSuffix}`;
    }
    return `${sign}${scaled}${suffix}`;
  }
  const whole = Math.round(a);
  if (whole >= 1000) return `${sign}1K`; // 999.6 rounds to a thousand
  return `${sign}${whole}`;
}

/** The first line of a text (the concept's headline), trimmed; null when there is none. */
export function firstLine(text: string | null | undefined): string | null {
  const line = (text ?? '').split(/\r?\n/).map((l) => l.trim()).find(Boolean);
  return line || null;
}

/** The Age cell: an iconic moment in years ("14 y", "<1 y"), anything else in days ("3 d", "<1 d"); null when the post date is unknown. */
export function ageCell(postedAt: string | null | undefined, tier: Tier, now: number): { days: number; label: string } | null {
  const days = ageDays(postedAt, now);
  if (days == null) return null;
  if (tier === 'iconic') {
    const years = Math.floor(days / YEAR_DAYS);
    return { days, label: years < 1 ? '<1 y' : `${years} y` };
  }
  const d = Math.floor(days);
  return { days, label: d < 1 ? '<1 d' : `${d} d` };
}

/** The mode a pick is planned as: the owner's choice wins over the analyst's proposal; null when neither said. */
export function pickMode(p: { owner_mode?: OwnerMode | null; proposed_mode?: string | null }): OwnerMode | null {
  const mode = p.owner_mode ?? p.proposed_mode;
  return mode === 'dropin' || mode === 'recreate' ? mode : null;
}

export interface LongListRow {
  pick: ViralPick;
  tier: Tier;
  /** The concept's first line, else the hook, the creator or the URL. */
  title: string;
  /** Recognisability: iconic moments only. */
  rec: number | null;
  views: number | null;
  age: { days: number; label: string } | null;
  velocity: number | null;
  outlier: number | null;
  sat: number | null;
  fit: number | null;
  feas: number | null;
  mode: OwnerMode | null;
  credits: number;
  /** true when `credits` is the terminal's own estimate (the analyst gave none). */
  creditsEstimated: boolean;
  score: number | null;
}

/** One table row of a pick: what each column shows (and sorts by). */
export function longListRow(p: ViralPick, now: number): LongListRow {
  const tier = tierOf(p, now).tier;
  const iconic = tier === 'iconic';
  const mode = pickMode(p);
  const given = finite(p.est_credits);
  return {
    pick: p,
    tier,
    title: firstLine(p.concept) ?? (p.hook ? `“${p.hook}”` : null) ?? p.creator_handle ?? p.url,
    rec: iconic ? finite(p.recognisability) : null,
    views: iconic ? finite(p.original_views) ?? finite(p.views) : finite(p.views),
    age: ageCell(p.posted_at, tier, now),
    velocity: pickVelocity({ velocity: p.velocity, views: p.views, posted_at: p.posted_at }, now),
    outlier: finite(p.outlier_x),
    sat: finite(p.saturation_count),
    fit: finite(p.fit),
    feas: finite(p.feasibility),
    mode,
    credits: given ?? estimateCredits(mode ?? 'dropin', CREDITS.defaultSeconds, p.owner_music ?? (mode === 'recreate' ? 'ai_beat' : 'original')),
    creditsEstimated: given == null,
    score: finite(p.total_score),
  };
}

const MODE_ORDER: Record<string, number> = { dropin: 0, recreate: 1 };

/** The value a column sorts by: a number or a lower-case text; null sorts last whichever way the column runs. */
export function sortValue(row: LongListRow, key: LongListKey): number | string | null {
  switch (key) {
    case 'clip': return row.title.toLowerCase();
    case 'character': return (row.pick.character_name ?? row.pick.character_slug ?? '').toLowerCase() || null;
    case 'tier': return TIERS.indexOf(row.tier);
    case 'rec': return row.rec;
    case 'views': return row.views;
    case 'age': return row.age?.days ?? null;
    case 'velocity': return row.velocity;
    case 'outlier': return row.outlier;
    case 'sat': return row.sat;
    case 'fit': return row.fit;
    case 'feas': return row.feas;
    case 'mode': return row.mode == null ? null : MODE_ORDER[row.mode];
    case 'credits': return row.credits;
    case 'score': return row.score;
  }
}

const tieBreak = (a: LongListRow, b: LongListRow) =>
  Date.parse(a.pick.created_at) - Date.parse(b.pick.created_at) || a.pick.id.localeCompare(b.pick.id);

/**
 * The default order: by tier (Broke the internet, Viral now, Up and coming, Ready to drop in); inside Broke the internet the most
 * recognisable first, then the score; inside the others the score (unscored last); then the oldest filed first.
 */
export function compareDefault(a: LongListRow, b: LongListRow): number {
  const byTier = TIERS.indexOf(a.tier) - TIERS.indexOf(b.tier);
  if (byTier) return byTier;
  if (a.tier === 'iconic') {
    const byRec = Number(a.rec == null) - Number(b.rec == null) || (b.rec ?? 0) - (a.rec ?? 0);
    if (byRec) return byRec;
  }
  return Number(a.score == null) - Number(b.score == null) || (b.score ?? 0) - (a.score ?? 0) || tieBreak(a, b);
}

/** Rows in the order `sort` asks for. A column with no value in a row puts that row last, ascending or descending. */
export function sortLongList(rows: ReadonlyArray<LongListRow>, sort: LongListSort): LongListRow[] {
  if (sort.key === 'default') return [...rows].sort(compareDefault);
  const key = sort.key;
  const sign = sort.dir === 'asc' ? 1 : -1;
  return [...rows].sort((a, b) => {
    const x = sortValue(a, key);
    const y = sortValue(b, key);
    if (x == null || y == null) return Number(x == null) - Number(y == null) || compareDefault(a, b);
    const cmp = typeof x === 'number' && typeof y === 'number' ? x - y : String(x).localeCompare(String(y));
    return cmp * sign || compareDefault(a, b);
  });
}

/** A tap on a column header: the same column flips its direction, another column starts in its natural direction. */
export function nextSort(current: LongListSort, key: LongListKey): LongListSort {
  if (current.key === key) return { key, dir: current.dir === 'asc' ? 'desc' : 'asc' };
  const column = LONG_LIST_COLUMNS.find((c) => c.key === key);
  return { key, dir: column?.first ?? 'desc' };
}

/** The header's aria-sort. */
export function ariaSort(current: LongListSort, key: LongListKey): 'ascending' | 'descending' | 'none' {
  if (current.key !== key) return 'none';
  return current.dir === 'asc' ? 'ascending' : 'descending';
}

export interface LongListFilter {
  /** A character slug, or `all`. */
  character: string;
  tier: Tier | 'all';
}

/** The rows of the new picks that pass the filters (a character filter keeps only that character's picks). */
export function longListRows(picks: ReadonlyArray<ViralPick>, filter: LongListFilter, now: number): LongListRow[] {
  return picks
    .filter((p) => p.status === 'new')
    .filter((p) => filter.character === 'all' || p.character_slug === filter.character)
    .map((p) => longListRow(p, now))
    .filter((r) => filter.tier === 'all' || r.tier === filter.tier);
}

/** How many new picks each character chip and each tier chip stands for (tiers counted inside the chosen character). */
export function longListCounts(
  picks: ReadonlyArray<ViralPick>,
  character: string,
  roster: ReadonlyArray<{ slug: string }>,
  now: number,
): { characters: Record<string, number>; tiers: Record<Tier | 'all', number> } {
  const fresh = picks.filter((p) => p.status === 'new');
  const characters: Record<string, number> = { all: fresh.length };
  for (const c of roster) characters[c.slug] = fresh.filter((p) => p.character_slug === c.slug).length;
  const tiers: Record<Tier | 'all', number> = { all: 0, iconic: 0, viral_now: 0, rising: 0, gallery: 0 };
  for (const p of fresh) {
    if (character !== 'all' && p.character_slug !== character) continue;
    tiers.all += 1;
    tiers[tierOf(p, now).tier] += 1;
  }
  return { characters, tiers };
}

/** "≈310K/day" style text for the Views/day cell; an em dash when unknown. */
export const perDay = (v: number | null) => (v == null ? '—' : compactCount(v));

/** "1,240×" / "18.2×" for the Outlier cell. */
export function outlierCell(x: number | null): string {
  if (x == null) return '—';
  return x >= 100 ? `${Math.round(x).toLocaleString('en-GB')}×` : `${Number(x.toFixed(1))}×`;
}

/** A 0-10 sub-score as the table prints it ("9", "8.5"). */
export const scoreCell = (v: number | null) => (v == null ? '—' : String(Number(v.toFixed(1))));


/** The Picks page's two views: the cards (the default) and the long list. */
export type PicksView = 'cards' | 'list';
export const PICKS_VIEW_KEY = 'oddeyes.picks.view';

/** Which view to show: a `view=list|cards` deep link wins, else the viewer's last choice, else the cards. */
export function picksView(query: string, stored: string | null | undefined): PicksView {
  const asked = new URLSearchParams(query).get('view');
  if (asked === 'list' || asked === 'cards') return asked;
  return stored === 'list' ? 'list' : 'cards';
}
