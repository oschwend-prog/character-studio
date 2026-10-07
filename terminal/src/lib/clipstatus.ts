// Terminal v2, Clips page (owner 2026-10-07): one plain chip per dropped clip instead of the 8-step stepper, and the filters over
// them. Pure functions over v_tracker rows (drop_card, migrations 0012-0013); no browser.
import { FINISHED_STATES } from './finished';
import { IN_PRODUCTION_STATES } from './rules';
import type { TrackerRow } from './types';

export type ClipChip = 'adding' | 'checking' | 'pick' | 'ready' | 'making' | 'done' | 'blocked' | 'failed';

export const CHIP_LABEL: Record<ClipChip, string> = {
  adding: 'Adding',
  checking: 'Checking',
  pick: 'Pick a character',
  ready: 'Ready',
  making: 'Making',
  done: 'Done',
  blocked: 'Blocked',
  failed: 'Failed',
};

const REACHED_OK = (s: TrackerRow['clip_state']): boolean => s != null && (FINISHED_STATES as ReadonlyArray<string>).includes(s);
const IN_PRODUCTION = (s: TrackerRow['clip_state']): boolean => s != null && IN_PRODUCTION_STATES.includes(s);

/**
 * Where a dropped clip is, in one word. The clip's own state counts first where it is proof of progress, the drop's state
 * (studio.drop) decides the rest:
 * 1. Done: the clip reached the owner's OK or later (awaiting approval, approved, scheduled, posted), or the drop is made. A
 *    rejected or dropped clip is done only when the drop is made; otherwise the drop's state still decides.
 * 2. Blocked and Failed come from the drop state, even when a half-made clip exists (its Try again is on the card).
 * 3. Making: the drop is making, or Make it was tapped and no clip exists yet, or the clip is between planned and mastered
 *    (the drop card can lag behind its clip).
 * 4. Adding (uploading), Checking (checking, waiting), then Ready only when the owner chose the character (character_by
 *    'owner'); anything else is Pick a character: the studio chose it (character_by 'studio', the Drop box's Recommend) or no
 *    one recorded it. A drop from before migration 0013 has no character_by and counts as not yet chosen here, even though
 *    characterMenu reads absent as the owner's for its menu: those drops had their character set by the studio, and a Ready chip
 *    could lead to a paid Make it for a character he never chose; at worst he confirms it with one tap.
 * A row with no drop card (a scan pick) follows its clip alone and is otherwise still being checked.
 */
export function clipChip(row: TrackerRow): ClipChip {
  const d = row.drop_card;
  if (REACHED_OK(row.clip_state) || d?.state === 'made') return 'done';
  if (d?.state === 'blocked') return 'blocked';
  if (d?.state === 'failed') return 'failed';
  if (d?.state === 'making' || (row.make_requested_at && !row.clip_id) || IN_PRODUCTION(row.clip_state)) return 'making';
  switch (d?.state) {
    case 'uploading':
      return 'adding';
    case 'ready':
      return d.character_by === 'owner' ? 'ready' : 'pick';
    default:
      return 'checking'; // checking, waiting, or a row with no card
  }
}

export type ClipFilter = 'all' | 'pick' | 'ready' | 'making' | 'done' | 'problems';

/** The Clips page's filter: only dropped clips (rows with a drop card), in the order given; problems are the blocked and the failed. */
export function filterClips(rows: ReadonlyArray<TrackerRow>, f: ClipFilter): TrackerRow[] {
  const clips = rows.filter((r) => r.drop_card);
  if (f === 'all') return clips;
  return clips.filter((r) => {
    const chip = clipChip(r);
    return f === 'problems' ? chip === 'blocked' || chip === 'failed' : chip === f;
  });
}
