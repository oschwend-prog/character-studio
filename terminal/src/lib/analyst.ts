// The analyst's data on a pick card (owner request 2026-10-05): how old the video is, how fast it is climbing, how much people
// react to it, how crowded the idea is, which of the character's traits it matches and what the local check of its clip
// found. Pure rules, no browser: studio/favorites.py has the same ones (velocity_per_day, engagement_rates, saturation_score)
// and terminal/src/lib/parity-cases.json holds the cases both sides must agree on.
import { formatViews } from './format';
import { SATURATION_STEPS, TIER_RULES } from './scanConfig';
import type { ClipAnalysis, Engagement } from './types';

export const DAY_MS = 86_400_000;

const finite = (v: unknown): number | null => (typeof v === 'number' && Number.isFinite(v) ? v : null);

/**
 * When a video was posted, as an epoch: an ISO date or time. A date-time without an offset is UTC (like the Python side),
 * not the browser's own zone. null for anything that is not a date.
 */
export function parseMoment(raw: string | null | undefined): number | null {
  if (typeof raw !== 'string' || !raw.trim()) return null;
  const text = raw.trim();
  const noOffset = /^\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}(:\d{2}(\.\d+)?)?$/.test(text);
  const at = Date.parse(noOffset ? `${text.replace(' ', 'T')}Z` : text);
  return Number.isNaN(at) ? null : at;
}

/** Days since the video was posted (can be a fraction), or null when the post date is unknown. */
export function ageDays(postedAt: string | null | undefined, now: number): number | null {
  const at = parseMoment(postedAt);
  return at == null ? null : (now - at) / DAY_MS;
}

/**
 * Views per day since posting, to the whole view; null when the views or the age are unknown. A clip posted a few hours ago
 * is divided by one day (`velocity_min_age_days`), never by a fraction of one.
 */
export function velocityPerDay(views: number | null | undefined, age: number | null | undefined): number | null {
  const v = finite(views);
  const a = finite(age);
  if (v == null || a == null || v < 0) return null;
  return Math.floor(v / Math.max(a, TIER_RULES.velocity_min_age_days) + 0.5);
}

/** The velocity a pick carries: the one stored when it was filed (views of that day), else views / age now. */
export function pickVelocity(p: { velocity?: number | null; views: number | null; posted_at?: string | null }, now: number): number | null {
  const stored = finite(p.velocity);
  if (stored != null && stored >= 0) return stored;
  return velocityPerDay(p.views, ageDays(p.posted_at, now));
}

export interface EngagementRates {
  /** (likes + comments + shares + saves) / views over the counts that are known. */
  engagement_rate: number;
  /** shares / views; null when the shares are not known. */
  share_rate: number | null;
}

/** Engagement and share rate of a video; null without a view count or without any engagement count. */
export function engagementRates(engagement: Engagement | null | undefined, views: number | null | undefined): EngagementRates | null {
  const v = finite(views);
  if (v == null || v <= 0 || !engagement || typeof engagement !== 'object') return null;
  const counts = (['likes', 'comments', 'shares', 'saves'] as const)
    .map((k) => [k, finite(engagement[k])] as const)
    .filter((e): e is readonly [(typeof e)[0], number] => e[1] != null && e[1] >= 0);
  if (!counts.length) return null;
  const shares = counts.find(([k]) => k === 'shares');
  return { engagement_rate: counts.reduce((n, [, c]) => n + c, 0) / v, share_rate: shares ? shares[1] / v : null };
}

/** The 0-10 saturation sub-score from the similar outliers found in the last 7 days: 8+ is 3, 4-7 is 5, 1-3 is 8, none is 10. */
export function saturationScore(count: number): number {
  if (!Number.isInteger(count) || count < 0) throw new Error(`saturation_count must be a whole number of 0 or more, got ${count}`);
  return (SATURATION_STEPS.find((s) => count >= s.min_count) ?? SATURATION_STEPS[SATURATION_STEPS.length - 1]).score;
}

// ---- the words on the card ----------------------------------------------------------------------------------------------

/** "posted today", "posted 6 days ago", "posted 4 months ago", "posted 2 years ago"; null when the date is unknown. */
export function postedLabel(days: number | null): string | null {
  if (days == null || !Number.isFinite(days)) return null;
  if (days < 1) return 'posted today';
  const d = Math.round(days);
  if (d < 60) return `posted ${d} ${d === 1 ? 'day' : 'days'} ago`;
  if (days < 365) return `posted ${Math.round(days / 30.44)} months ago`;
  const years = Math.floor(days / 365.25);
  return `posted ${years} ${years === 1 ? 'year' : 'years'} ago`;
}

/** "≈310K views/day": three digits above 100K (333K, not 333.3K), one decimal for the millions and the small numbers. */
export function velocityLabel(v: number | null): string | null {
  if (v == null) return null;
  const words = v >= 100_000 && v < 1_000_000 ? `${Math.round(v / 1000)}K` : formatViews(v);
  return `≈${words} views/day`;
}

/** 0.048 -> "4.8%", 0.12 -> "12%", 0.005 -> "0.5%". */
export function formatRate(rate: number): string {
  const pct = rate * 100;
  return `${pct < 10 ? pct.toFixed(1) : Math.round(pct)}%`;
}

export interface CheckChip {
  text: string;
  tone: 'ok' | 'warn' | 'bad' | 'plain';
}

const CAMERA_WORDS = { static: 'Static camera', handheld: 'Handheld camera', moving: 'Moving camera' } as const;

/** The "Clip check" row: what the local check and the look at the contact sheet found, as short chips with a tone. */
export function clipCheckChips(a: ClipAnalysis): CheckChip[] {
  const chips: CheckChip[] = [
    { text: a.people_count === 0 ? 'No people' : `${a.people_count} ${a.people_count === 1 ? 'person' : 'people'}`, tone: 'plain' },
  ];
  if (a.main_subject) chips.push({ text: a.main_subject, tone: 'plain' });
  chips.push({ text: CAMERA_WORDS[a.camera] ?? String(a.camera), tone: a.camera === 'static' ? 'ok' : 'warn' });
  chips.push({ text: a.watermark ? 'Watermark or handle' : 'No watermark', tone: a.watermark ? 'bad' : 'ok' });
  chips.push({ text: a.overlay ? 'Text on screen' : 'No text overlay', tone: a.overlay ? 'bad' : 'ok' });
  chips.push({ text: a.minors ? 'Child visible' : 'No children', tone: a.minors ? 'bad' : 'ok' });
  const w = a.best_window;
  if (w && Number.isFinite(w.start_s) && Number.isFinite(w.end_s)) {
    chips.push({ text: `Best ${trim1(w.start_s)}-${trim1(w.end_s)} s (${trim1(w.end_s - w.start_s)} s)`, tone: 'plain' });
  }
  if (finite(a.bpm) != null) chips.push({ text: `${Math.round(a.bpm as number)} bpm`, tone: 'plain' });
  return chips;
}
const trim1 = (n: number) => String(Math.round(n * 10) / 10);

export interface PickFacts {
  posted: string | null;
  velocity: string | null;
  /** "4.8% engaged" and "1.2% shares": only the ones that can be worked out. */
  engagement: string | null;
  shares: string | null;
  saturation: string | null;
  /** The traits the video matches, as chips ("Matches: slick upright dance · hits every beat" on the card). */
  matches: string[];
  why: string | null;
  check: CheckChip[] | null;
  checkNotes: string | null;
}

/** Everything the card says beyond its top line: age, velocity, reactions, the traits it matches, why, and the clip check. */
export function pickFacts(
  p: {
    views: number | null;
    posted_at?: string | null;
    velocity?: number | null;
    engagement?: Engagement | null;
    saturation_count?: number | null;
    trait_matches?: string[] | null;
    why?: string | null;
    analysis?: ClipAnalysis | null;
  },
  now: number,
): PickFacts {
  const rates = engagementRates(p.engagement, p.views);
  const sat = finite(p.saturation_count);
  return {
    posted: postedLabel(ageDays(p.posted_at, now)),
    velocity: velocityLabel(pickVelocity(p, now)),
    engagement: rates ? `${formatRate(rates.engagement_rate)} engaged` : null,
    shares: rates?.share_rate != null ? `${formatRate(rates.share_rate)} shares` : null,
    saturation: sat != null && Number.isInteger(sat) && sat >= 0 ? (sat === 0 ? 'no copies this week' : `${sat} similar ${sat === 1 ? 'video' : 'videos'} this week`) : null,
    matches: Array.isArray(p.trait_matches) ? p.trait_matches.filter((m): m is string => typeof m === 'string' && m.trim() !== '') : [],
    why: typeof p.why === 'string' && p.why.trim() ? p.why.trim() : null,
    check: p.analysis && typeof p.analysis === 'object' ? clipCheckChips(p.analysis) : null,
    checkNotes: p.analysis?.notes?.trim() || null,
  };
}
