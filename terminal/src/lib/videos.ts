// Terminal v2, Videos page (owner 2026-10-07): the videos being made and the ones scheduled. Pure functions over the snapshot;
// no browser.
import { clipChip } from './clipstatus';
import { IN_PRODUCTION_STATES } from './rules';
import type { LibraryClip, Snapshot, TrackerRow } from './types';

export const isTrackerRow = (x: TrackerRow | LibraryClip): x is TrackerRow => 'pick_id' in x;

const NO_SLOT = Number.MAX_SAFE_INTEGER;

/** The slot a scheduled clip goes out at: its live posts' first slot (else its posts'), as the character pipeline reads it. */
function slotOf(c: LibraryClip): number {
  const live = c.posts.filter((p) => p.status === 'scheduled' || p.status === 'posting');
  const slots = (live.length ? live : c.posts).map((p) => Date.parse(p.scheduled_for)).filter((t) => !Number.isNaN(t));
  return slots.length ? Math.min(...slots) : NO_SLOT;
}

/**
 * The Videos page's two groups. Making: the tracker rows whose chip is Making, then the library clips in production that no
 * row already shows (a clip is listed once, by its row), the newest clip first. Scheduled: the approved and scheduled library
 * clips, the soonest slot first, a clip without a slot last.
 */
export function videoGroups(data: Snapshot): { making: (TrackerRow | LibraryClip)[]; scheduled: LibraryClip[] } {
  const rows = data.tracker.filter((r) => clipChip(r) === 'making');
  const listed = new Set(rows.map((r) => r.clip_id).filter((id): id is string => id != null));
  const clips = data.library
    .filter((c) => IN_PRODUCTION_STATES.includes(c.state) && !listed.has(c.id))
    .sort((a, b) => (Date.parse(b.created_at) || 0) - (Date.parse(a.created_at) || 0) || a.id.localeCompare(b.id));
  const scheduled = data.library
    .filter((c) => c.state === 'scheduled' || c.state === 'approved')
    .sort((a, b) => slotOf(a) - slotOf(b) || a.id.localeCompare(b.id));
  return { making: [...rows, ...clips], scheduled };
}
