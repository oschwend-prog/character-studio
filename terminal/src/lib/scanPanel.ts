// "How we scan": what the Picks page tells the owner about the scanning process, as plain data. Everything static comes from
// scanConfig.ts (a copy of config/scan.json, pinned equal by analyst.test.ts) and the shared tier rule, so the words on the panel can
// never drift from the numbers the scanner and the categories actually use. Pure functions, no browser.
import { formatViews, londonDate, londonTime } from './format';
import {
  CREDITS, TIER_LABELS, TIERS, estimateCredits, tierOf, type ScannerStatus,
} from './rules';
import {
  GLOBAL_REJECT_RULES, SCAN_ACCESS, SCAN_BUDGET, SCAN_CHARACTERS, SCAN_DEFAULTS, TIER_RULES, VIDEO_REQUIREMENTS, type ScanTheme,
} from './scanConfig';
import type { Tier } from './types';

const times = (n: number) => `${n}×`;

export interface TierRuleLine {
  id: Tier | 'fallback';
  label: string;
  rule: string;
}

/**
 * The category rule in the order it is applied (the first line that fits a video wins), worded from `TIER_RULES`: the same
 * numbers `defaultTier` and studio/favorites.py use. An explicit category the analyst set always wins over all of it.
 */
export function tierRuleLines(): TierRuleLine[] {
  const r = TIER_RULES;
  return [
    { id: 'gallery', label: TIER_LABELS.gallery, rule: 'A clip from Higgsfield’s Genjutsu gallery, already clean and trimmed' },
    { id: 'iconic', label: TIER_LABELS.iconic, rule: `Older than ${r.iconic_min_age_days} days, or ${formatViews(r.iconic_min_views)} views or more` },
    {
      id: 'viral_now',
      label: TIER_LABELS.viral_now,
      rule: `Posted within ${r.viral_now_max_age_days} days with an outlier of ${times(r.viral_now_min_outlier)} or more, or climbing at ${formatViews(r.viral_now_min_velocity_per_day)} views a day or more`,
    },
    { id: 'rising', label: TIER_LABELS.rising, rule: `Posted within ${r.rising_max_age_days} days with an outlier of ${times(r.rising_min_outlier)} or more` },
    {
      id: 'fallback',
      label: 'Anything else',
      rule: `${TIER_LABELS.viral_now} up to ${r.fallback_viral_now_max_age_days} days old, ${TIER_LABELS.iconic} after that (a video with no post date counts as ${TIER_LABELS.viral_now})`,
    },
  ];
}

/** The scan's filters, as the owner would say them (from `defaults` of scan.json). */
export function filterLines(): string[] {
  const d = SCAN_DEFAULTS;
  return [
    `Posted in the last ${d.posted_within_days} days`,
    `${formatViews(d.viewsMin)} views or more`,
    `Outlier score ${times(d.outlierScoreMin)} or more: views against the creator’s own median`,
    `${d.durationMax} seconds or shorter`,
    `Up to ${d.resultsPerPlatform} results per platform (Instagram Reels and TikTok)`,
    d.descriptionLanguage.map((l) => (l === 'en' ? 'English' : l)).join(', ') + ' descriptions',
    d.collapseByCreator ? 'One result per creator' : 'Every result',
  ];
}

/** "Culture/Region: US/UK English-speaking; Global: true; Demographics: dog lovers...;" -> the region and the audience. */
export function parseAudience(query: string): { region: string | null; audience: string | null } {
  const field = (name: string) => new RegExp(`${name}:\\s*([^;]+);?`, 'i').exec(query)?.[1]?.trim() ?? null;
  return { region: field('Culture/Region'), audience: field('Demographics') };
}

export interface ScanCharacterView {
  slug: string;
  name: string;
  region: string | null;
  audience: string | null;
  themes: ReadonlyArray<ScanTheme>;
  fitRules: ReadonlyArray<string>;
  /** Why it is not scanned yet (the Outsider waits for the voice lane); null when it is. */
  inactive: string | null;
}

/** What is scanned for each character of the roster, in roster order (a character with no scan settings is left out). */
export function scanCharacters(roster: ReadonlyArray<{ slug: string; name: string }>): ScanCharacterView[] {
  return roster.flatMap((c) => {
    const cfg = SCAN_CHARACTERS[c.slug];
    if (!cfg) return [];
    return [{ slug: c.slug, name: c.name, ...parseAudience(cfg.audienceQuery), themes: cfg.rotation, fitRules: cfg.fit_rules, inactive: cfg.status ?? null }];
  });
}

export interface TierExample {
  tier: Tier;
  label: string;
  /** How many of the current picks are in this category. */
  count: number;
  /** The best-scored one's hook (or its creator), as an example; null when the category is empty. */
  example: string | null;
}

/** The four categories with how many of the current picks each holds and one example (the best score, gallery last as a backup). */
export function tierExamples(
  picks: ReadonlyArray<{
    tier?: string | null; gallery?: boolean | null; outlier_x: number | null; posted_at?: string | null; views?: number | null; velocity?: number | null;
    total_score: number | null; hook: string | null; creator_handle: string | null;
  }>,
  now: number,
): TierExample[] {
  return TIERS.map((tier) => {
    const mine = picks
      .filter((p) => tierOf(p, now).tier === tier)
      .sort((a, b) => (b.total_score ?? -1) - (a.total_score ?? -1));
    const best = mine[0];
    return { tier, label: TIER_LABELS[tier], count: mine.length, example: best ? (best.hook ? `“${best.hook}”` : best.creator_handle) : null };
  });
}

export interface BudgetView {
  vidiq: {
    perSearch: number;
    perWatch: number;
    /** Watches a week in the plan (0: the free check of an approved clip replaces them). */
    watchesPerWeek: number;
    plan: number;
    used: number;
    /** Share of the plan used this month, 0-100. */
    pct: number;
    /** What the weekly plan of scans and watches adds up to, and the monthly equivalent. */
    weekly: number;
    monthlyNeed: number;
    overPlan: boolean;
    weeklyLine: string;
    /** Below this balance the day's search is skipped. */
    floor: number;
    floorLine: string;
  };
  higgsfield: { label: string; credits: number; note: string }[];
}

/** vidIQ credits per search and per watch against the plan, and what a clip costs in Higgsfield credits per mode. */
export function budgetView(vidiqUsedThisMonth: number): BudgetView {
  const b: { scans_per_week: number; scan_days: ReadonlyArray<string>; breakdowns_per_week: number; credits_per_scan: number; credits_per_watch: number; vidiq_monthly_credits: number; balance_floor: number } = SCAN_BUDGET;
  const searches = b.scans_per_week * b.credits_per_scan;
  const watches = b.breakdowns_per_week * b.credits_per_watch;
  const weekly = searches + watches;
  const monthlyNeed = Math.round((weekly * 52) / 12);
  const days = b.scan_days.length === 5 && b.scan_days.join() === 'Mon,Tue,Wed,Thu,Fri' ? 'one each weekday' : `on ${b.scan_days.join(', ')}`;
  return {
    vidiq: {
      perSearch: b.credits_per_scan,
      perWatch: b.credits_per_watch,
      watchesPerWeek: b.breakdowns_per_week,
      plan: b.vidiq_monthly_credits,
      used: vidiqUsedThisMonth,
      pct: Math.min(100, (vidiqUsedThisMonth * 100) / b.vidiq_monthly_credits),
      weekly,
      monthlyNeed,
      overPlan: monthlyNeed > b.vidiq_monthly_credits,
      weeklyLine:
        b.breakdowns_per_week > 0
          ? `${b.scans_per_week} searches (${searches}) + up to ${b.breakdowns_per_week} watches (${watches}) a week = ${weekly} credits`
          : `${b.scans_per_week} searches a week, ${days} (${searches} credits), about ${monthlyNeed} a month; no watches: the free check of an approved clip replaces them`,
      floor: b.balance_floor,
      floorLine: `Below ${b.balance_floor} credits the day’s search is skipped (the run says so, with the refill date)`,
    },
    higgsfield: [
      { label: 'Drop-in, 8 s window', credits: estimateCredits('dropin', CREDITS.defaultSeconds, 'original'), note: `${CREDITS.dropinPerSecond} a second + ${CREDITS.stills} for the stills; the clip’s own audio is free` },
      { label: 'Drop-in with an AI beat', credits: estimateCredits('dropin', CREDITS.defaultSeconds, 'ai_beat'), note: `${CREDITS.aiBeat} more for our own beat` },
      { label: 'Recreate', credits: CREDITS.recreate, note: 'a synthetic driver, the scene still and the transfer' },
    ],
  };
}

export interface LastScanView {
  when: string;
  line: string;
  queries: string[];
  credits: number;
}

/** "Tue 6 Oct 08:00" and "9 outliers found, 4 picks filed (1 auto-approved, 1 held, 2 skipped)" from the Scanner card's last run. */
export function lastScanView(last: ScannerStatus['last']): LastScanView | null {
  if (!last) return null;
  const s = last.scan;
  const plural = (n: number, one: string, many: string) => `${n} ${n === 1 ? one : many}`;
  return {
    when: `${londonDate(last.at)} ${londonTime(last.at)}`,
    line: `${plural(s.outliers, 'outlier', 'outliers')} found, ${plural(s.picks_added, 'pick', 'picks')} filed (${s.auto_approved} auto-approved, ${s.held} held, ${s.skipped} skipped)`,
    queries: s.queries,
    credits: s.vidiq_credits,
  };
}

export { GLOBAL_REJECT_RULES, SCAN_ACCESS, VIDEO_REQUIREMENTS };
