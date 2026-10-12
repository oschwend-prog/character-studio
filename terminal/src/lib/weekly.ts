// The weekly review on Today (learning plan 6.1 and build item 11, Task 16): the latest `weekly` run of studio.runs, read defensively
// (it is JSON written by the cloud job `studio review weekly`, shape documented in studio/weekly.py), and the score test's label that
// goes beside a clip's score. Pure functions; no browser.
import { londonDayKey } from './format';
import type { RunRow } from './types';

/** What Today says before the first review has run. */
export const FIRST_WEEKLY_NOTE = 'The first weekly review runs on Monday 19 October.';
/** What Today says once Monday 19 October is over and still no review exists: the job did not deliver. */
export const NO_WEEKLY_NOTE = 'No weekly review yet: check the studio-weekly job on GitHub.';
/** The London day the first review is due (YYYY-MM-DD): from the day after it, no review means something is wrong. */
const FIRST_WEEKLY_DAY = '2026-10-19';

/** The one muted line when there is no review: "due on Monday" until the end of that Monday (London), then "check the job". */
export function emptyWeeklyNote(now: Date = new Date()): string {
  return londonDayKey(now) <= FIRST_WEEKLY_DAY ? FIRST_WEEKLY_NOTE : NO_WEEKLY_NOTE;
}

/** One character of the digest: his title line and his five labelled lines ("1 Result    ..."), or the one line "no posts yet". */
export interface WeeklyCharacter {
  slug: string;
  name: string;
  /** "Reginald · week of 12 Oct · bar: not yet (9 of 20 posts, day 14 of 28)". */
  title: string;
  /** The bar phrase alone: "not yet (9 of 20 posts, day 14 of 28)"; empty when the run did not carry it. */
  bar: string;
  lines: string[];
}

export interface WeeklyDigest {
  /** The Monday of the week reviewed, YYYY-MM-DD. */
  week: string;
  /** "week of 12 Oct". */
  label: string;
  /** The run's status: `ok`, or `error` when a part of the review failed (its notes say which). */
  status: string;
  ranAt: string;
  /** The run's notes (parts with no data yet, parts that failed); shown on the card only when the status is not `ok`. */
  notes: string[];
  /** The studio header: credits against the cap and the cost per 1K views; the warnings and the proposals waiting. */
  header: string[];
  characters: WeeklyCharacter[];
  /** The compare link of the weekly pull request (an https address), or null when nothing is waiting. */
  proposalUrl: string | null;
}

const MONTHS = ['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
const DAY = /^(\d{4})-(\d{2})-(\d{2})$/;

/** "2026-10-12" -> "week of 12 Oct"; a text that is not a date is kept as it is. */
export function weekLabel(week: string): string {
  const m = DAY.exec(week);
  if (!m || Number(m[2]) < 1 || Number(m[2]) > 12) return week;
  return `week of ${Number(m[3])} ${MONTHS[Number(m[2]) - 1]}`;
}

const isObject = (v: unknown): v is Record<string, unknown> => typeof v === 'object' && v !== null && !Array.isArray(v);
const strings = (v: unknown): string[] => (Array.isArray(v) ? v.filter((x): x is string => typeof x === 'string') : []);

/** The digest of a `weekly` run, or null when the run is missing or its details are not a digest (a bad row never breaks Today). */
export function parseWeekly(run: RunRow | null | undefined): WeeklyDigest | null {
  const d = run?.details;
  if (!run || !isObject(d) || typeof d.week !== 'string' || !DAY.test(d.week) || !isObject(d.digest)) return null;
  const characters: WeeklyCharacter[] = [];
  for (const c of Array.isArray(d.digest.characters) ? d.digest.characters : []) {
    if (!isObject(c) || typeof c.slug !== 'string' || !c.slug || !Array.isArray(c.lines)) continue;
    const name = typeof c.name === 'string' && c.name ? c.name : c.slug;
    characters.push({
      slug: c.slug, name, title: typeof c.title === 'string' && c.title ? c.title : name, bar: typeof c.bar === 'string' ? c.bar : '', lines: strings(c.lines),
    });
  }
  const url = d.proposal_url;
  return {
    week: d.week,
    label: weekLabel(d.week),
    status: run.status,
    ranAt: run.finished_at ?? run.started_at,
    notes: strings(d.notes),
    header: strings(d.digest.header),
    characters,
    proposalUrl: typeof url === 'string' && url.startsWith('https://') ? url : null,
  };
}

const LABELLED = /^[1-5] (Result|Audience|Hook|Tests|Next)\s+(.*)$/s;

/** "1 Result    5 posts ..." -> { label: 'Result', text: '5 posts ...' }; any other line (no posts yet) is all text. */
export function splitLine(line: string): { label: string | null; text: string } {
  const m = LABELLED.exec(line);
  return m ? { label: m[1], text: m[2] } : { label: null, text: line };
}

// ---- the score test's label (test A, plan 3.2) ---------------------------------------------------------------------------------------

export type ScoreTestLabel = 'unproven' | 'validated' | 'failed' | 'uninformative';
const LABELS: ReadonlyArray<ScoreTestLabel> = ['unproven', 'validated', 'failed', 'uninformative'];

/** The score test as the latest weekly run reports it. Without a run (or with a run from before the test) it is unproven. */
export interface ScoreTestInfo {
  label: ScoreTestLabel;
  /** Posted drops counted so far (null = not known). */
  n: number | null;
  /** The n of the next look: 20, then 40. */
  needed: number | null;
  /** The look the label comes from (20 or 40); null before the first. */
  look: number | null;
}

const count = (v: unknown): number | null => (typeof v === 'number' && Number.isFinite(v) && v >= 0 ? v : null);

export function scoreTestOf(run: RunRow | null | undefined): ScoreTestInfo {
  const none: ScoreTestInfo = { label: 'unproven', n: null, needed: null, look: null };
  const t = isObject(run?.details) ? run.details.score_test : null;
  if (!isObject(t)) return none;
  const label = LABELS.find((l) => l === t.label);
  return label ? { label, n: count(t.n), needed: count(t.needed), look: count(t.look) } : none;
}

/** The small label beside a clip's score and its hover title; null when the test validated the score (nothing to caution). */
export interface ScoreNote {
  text: string;
  title: string;
}

export function scoreNote(info: ScoreTestInfo): ScoreNote | null {
  switch (info.label) {
    case 'validated':
      return null;
    case 'failed':
      return {
        text: 'unproven: does not predict views yet',
        title: `Score test: the score does not predict views yet${info.look != null ? ` (look at ${info.look} posts)` : ''}. Where a clip carries a trend, Make these puts the freshest first and the score second.`,
      };
    case 'uninformative':
      return { text: 'unproven', title: 'Score test: the scores were too close together to judge. Not a verdict.' };
    default:
      return {
        text: 'unproven',
        title: info.n != null && info.needed != null ? `Score test: ${info.n} of ${info.needed} posts so far. Not a verdict.` : 'Score test: no posts counted yet. Not a verdict.',
      };
  }
}

/** How Make these orders a character's ready clips: by the score (the default), or, when the score test failed, by the freshness
 * of the trend first and the score second (plan 3.2, "if failed"); `rankClips` applies it only while a visible clip carries a trend. */
export type RankOrder = 'score' | 'freshness';

export const rankOrderFor = (info: ScoreTestInfo): RankOrder => (info.label === 'failed' ? 'freshness' : 'score');
