// "In the works": where each approved pick is on its way to being posted. Pure functions over v_tracker rows (migration 0010): the
// 8-step mapping with its flags, who is listed (a posted one stays 7 days), the order, the grouping by character and the words the
// card shows. No browser.
import { londonTime, londonWeekday } from './format';
import { MUSIC_OPTIONS, defaultMusicForMode, tierOf } from './rules';
import type { OwnerMode, OwnerMusic, Tier, TrackerRow } from './types';

export const TRACKER_STEPS = ['Approved', 'Clip ready', 'Generating', 'Quality check', 'Video built', 'Your OK', 'Scheduled', 'Posted'] as const;
export type TrackerStepNumber = 1 | 2 | 3 | 4 | 5 | 6 | 7 | 8;
/** ok = moving; waiting = flagged (no clip yet, or stuck?); failed = something broke; dropped = given up (grey). */
export type TrackerState = 'ok' | 'waiting' | 'failed' | 'dropped';

export interface TrackerStep {
  step: TrackerStepNumber;
  state: TrackerState;
  /** The one-line reason of a flag (waiting, failed, dropped); null when the pick is simply moving. */
  reason: string | null;
  /** Since when the pick is at this step (ISO), for "2 h at Generating"; null when unknown. */
  since: string | null;
  /** A short line about the step itself (the clip check, the slot, "posting now"); null when there is nothing to add. */
  note: string | null;
  /** The owner's turn: "Review in Queue". */
  action: 'queue' | null;
  /** The step is complete (Posted, and done). */
  done: boolean;
}

/** More than this long at Generating or Quality check is flagged "stuck?". */
export const STUCK_HOURS = 6;
/** An approved pick with no clip ready after this long is flagged "no clip yet". */
export const NO_CLIP_HOURS = 24;
/** A posted pick stays listed this long after its post went out. */
export const POSTED_KEEP_DAYS = 7;

const HOUR = 3_600_000;
const ts = (iso: string | null | undefined) => (iso ? Date.parse(iso) : NaN);
const hoursSince = (iso: string | null | undefined, now: number) => (now - ts(iso)) / HOUR;

/** The mode the pick is made as: the clip's own mode once there is a clip, else the owner's choice, else the analyst's proposal. */
export function trackerMode(r: Pick<TrackerRow, 'clip_mode' | 'owner_mode' | 'proposed_mode' | 'fetch_failed'>): OwnerMode | null {
  if (r.clip_mode) return r.clip_mode;
  if (r.fetch_failed) return 'recreate'; // the clip could not be fetched: made automatically as a Recreate
  const mode = r.owner_mode ?? r.proposed_mode;
  return mode === 'dropin' || mode === 'recreate' ? mode : null;
}

/** "1 person · static camera · best 1.5-9.5 s": the clip check in one line. */
export function clipCheckLine(a: NonNullable<TrackerRow['analysis']>): string {
  const n = (x: number) => String(Number(x.toFixed(1)));
  const parts = [
    a.people_count === 1 ? '1 person' : `${a.people_count} people`,
    `${a.camera} camera`,
    a.best_window ? `best ${n(a.best_window.start_s)}-${n(a.best_window.end_s)} s` : null,
  ];
  return parts.filter(Boolean).join(' · ');
}

/** Why the clip is ready to make (step 2), or null when it is not yet: a gallery preset, a checked or attached clip, or a Recreate. */
export function clipReady(r: TrackerRow): string | null {
  if (r.gallery) return 'Genjutsu gallery clip: ready to drop in';
  if (r.analysis) return `Clip checked: ${clipCheckLine(r.analysis)}`;
  if (r.source_id) return 'Clip in the library';
  if (r.owner_clip_path) return 'Your clip is attached';
  if (trackerMode(r) === 'recreate') {
    return r.fetch_failed ? 'Recreate: the clip could not be fetched, we make our own driver' : 'Recreate: we make our own driver';
  }
  return null;
}

const STEP_OF_DROP = (r: TrackerRow): TrackerStepNumber => (r.clip_failure && r.credits_spent > 0 ? 4 : 3);

/**
 * Where an approved pick is (`step` 1-8) and how it is doing. In order:
 * 1. Approved: nothing else yet; flagged "no clip yet" after 24 h.  2. Clip ready: a gallery preset, a checked, stored or attached
 * clip, or a Recreate.  3. Generating: the clip is planned or generating (gen_failed: failed).  4. Quality check: generated,
 * qa_passed (qa_failed: failed, "re-roll once").  5. Video built: mastered.  6. Your OK: awaiting approval ("Review in Queue");
 * rejected: failed.  7. Scheduled: approved or scheduled with its post booked.  8. Posted: the post went out; a failed or
 * needs_check post is failed with its error. A dropped clip is `dropped` (grey) with its reason. More than 6 h at Generating or
 * Quality check is flagged "stuck?".
 */
export function trackerStep(r: TrackerRow, now: number): TrackerStep {
  const at = (step: TrackerStepNumber, state: TrackerState, extra: Partial<TrackerStep> = {}): TrackerStep => ({
    step, state, reason: null, since: r.clip_state_since, note: null, action: null, done: false, ...extra,
  });
  const stuck = (step: TrackerStepNumber, note: string | null = null): TrackerStep =>
    hoursSince(r.clip_state_since, now) > STUCK_HOURS ? at(step, 'waiting', { reason: 'stuck?', note }) : at(step, 'ok', { note });

  if (r.clip_state == null) {
    if (r.status === 'queued' || r.status === 'made') return at(3, 'ok', { since: r.approved_at, note: 'waiting for its clip to be created' });
    const ready = clipReady(r);
    if (ready) return at(2, 'ok', { since: r.approved_at, note: ready });
    return hoursSince(r.approved_at, now) > NO_CLIP_HOURS
      ? at(1, 'waiting', { since: r.approved_at, reason: 'no clip yet' })
      : at(1, 'ok', { since: r.approved_at });
  }
  switch (r.clip_state) {
    case 'planned':
      return stuck(3, 'queued for generation');
    case 'generating':
      return stuck(3);
    case 'gen_failed':
      return at(3, 'failed', { reason: r.clip_failure ?? 'generation failed: the next run tries again' });
    case 'generated':
      return stuck(4, 'waiting for the quality check');
    case 'qa_passed':
      return stuck(4, 'passed, being built');
    case 'qa_failed':
      return at(4, 'failed', { reason: `${r.clip_failure ?? 'quality check failed'}: re-roll once` });
    case 'mastered':
      return at(5, 'ok');
    case 'awaiting_approval':
      return at(6, 'ok', { action: 'queue', note: 'waiting for your OK' });
    case 'rejected':
      return at(6, 'failed', { reason: `rejected: ${r.clip_failure ?? 'no reason given'}` });
    case 'dropped': {
      const back = r.status === 'approved' || r.status === 'analysed' ? ' · back in line for the next run' : '';
      return at(STEP_OF_DROP(r), 'dropped', { reason: `${r.clip_failure ?? r.note ?? 'dropped by the daily run'}${back}` });
    }
    case 'approved':
    case 'scheduled':
    case 'posted': {
      if (r.post_status === 'failed') return at(8, 'failed', { reason: r.post_error ?? 'the post failed', since: r.post_scheduled_for });
      if (r.post_status === 'needs_check') {
        return at(8, 'failed', { reason: r.post_error ?? 'needs a check: is it live?', since: r.post_scheduled_for });
      }
      if (r.post_status === 'posting') return at(8, 'ok', { note: 'posting now', since: r.post_scheduled_for });
      if (r.post_status === 'posted' || r.clip_state === 'posted') {
        return at(8, 'ok', { since: r.post_posted_at ?? r.post_scheduled_for, done: true });
      }
      return at(7, 'ok', { note: r.post_scheduled_for ? slotLabel(r.post_scheduled_for) : 'booking its slot' });
    }
  }
}

/** Is the row listed: approved, analysed or queued, or made and not posted more than 7 days ago (v_tracker's own rule). */
export function inTracker(r: Pick<TrackerRow, 'status' | 'post_status' | 'post_posted_at' | 'post_scheduled_for'>, now: number): boolean {
  if (r.status === 'approved' || r.status === 'analysed' || r.status === 'queued') return true;
  if (r.status !== 'made') return false;
  if (r.post_status !== 'posted') return true;
  const went = ts(r.post_posted_at ?? r.post_scheduled_for);
  return !(now - went > POSTED_KEEP_DAYS * 24 * HOUR);
}

/** By scheduled time (the soonest first), then the ones without a post by approval time (the oldest first). */
export function compareTracker(a: TrackerRow, b: TrackerRow): number {
  const sa = ts(a.post_scheduled_for);
  const sb = ts(b.post_scheduled_for);
  const hasA = Number.isFinite(sa);
  const hasB = Number.isFinite(sb);
  if (hasA !== hasB) return hasA ? -1 : 1;
  if (hasA && hasB && sa !== sb) return sa - sb;
  return ts(a.approved_at) - ts(b.approved_at) || a.pick_id.localeCompare(b.pick_id);
}

export interface TrackerGroup {
  /** null = picks of no seeded character. */
  slug: string | null;
  name: string;
  rows: TrackerRow[];
}

/** One group per character of the roster that has rows (roster order), then the unassigned ones; each group in `compareTracker` order. */
export function groupTracker(rows: ReadonlyArray<TrackerRow>, roster: ReadonlyArray<{ slug: string; name: string }>, now: number): TrackerGroup[] {
  const listed = rows.filter((r) => inTracker(r, now));
  const known = new Set(roster.map((c) => c.slug));
  const groups: TrackerGroup[] = roster
    .map((c) => ({ slug: c.slug, name: c.name, rows: listed.filter((r) => r.character_slug === c.slug).sort(compareTracker) }))
    .filter((g) => g.rows.length > 0);
  const others = listed.filter((r) => !r.character_slug || !known.has(r.character_slug)).sort(compareTracker);
  if (others.length) groups.push({ slug: null, name: 'Unassigned', rows: others });
  return groups;
}

/** "Tue 19:00": a slot in London time. */
export function slotLabel(iso: string): string {
  return `${londonWeekday(iso)} ${londonTime(iso)}`;
}

/** "35 min", "2 h", "3 d": how long something has been going on. */
export function durationLabel(ms: number): string {
  const mins = Math.max(0, Math.floor(ms / 60_000));
  if (mins < 60) return `${Math.max(1, mins)} min`;
  const hours = Math.floor(mins / 60);
  if (hours < 48) return `${hours} h`;
  return `${Math.floor(hours / 24)} d`;
}

/** "2 h at Generating"; at Posted "posted 3 h ago" once done, else "slot 2 h ago"; null when the time is unknown or still to come. */
export function timeAtStep(s: TrackerStep, now: number): string | null {
  const since = ts(s.since);
  if (!Number.isFinite(since)) return null;
  if (s.done) return `posted ${durationLabel(now - since)} ago`;
  if (since > now) return null; // a slot still to come is shown as the slot itself
  if (s.step === 8) return `slot ${durationLabel(now - since)} ago`;
  return `${durationLabel(now - since)} at ${TRACKER_STEPS[s.step - 1]}`;
}

/** The music line of a card: the owner's choice, else the default of the mode. */
export function musicLabel(r: Pick<TrackerRow, 'owner_music' | 'clip_mode' | 'owner_mode' | 'proposed_mode' | 'fetch_failed'>): string {
  const mode = trackerMode(r);
  const music: OwnerMusic = r.owner_music ?? defaultMusicForMode(mode ?? 'analyst');
  return MUSIC_OPTIONS.find((o) => o.id === music)?.name.replace(' (default)', '') ?? music;
}

/** The card's title: the concept's first line, else the hook, else the URL. */
export function trackerTitle(r: Pick<TrackerRow, 'concept' | 'hook' | 'url'>): string {
  const line = (r.concept ?? '').split(/\r?\n/).map((l) => l.trim()).find(Boolean);
  return line || (r.hook ? `“${r.hook}”` : r.url);
}

/** The tier of a tracker row (the analyst's, else worked out from the numbers like a pick card). */
export function trackerTier(r: TrackerRow, now: number): Tier {
  return tierOf({ tier: r.tier, gallery: r.gallery, outlier_x: r.outlier_x, posted_at: r.posted_at, views: r.views, velocity: r.velocity }, now).tier;
}
