// Terminal v2, Videos page (owner 2026-10-07): the videos being made and the ones scheduled. Pure functions over the snapshot;
// no browser.
import { clipChip } from './clipstatus';
import { IN_PRODUCTION_STATES } from './rules';
import type { LibraryClip, Snapshot, TrackerRow } from './types';

export const isTrackerRow = (x: TrackerRow | LibraryClip): x is TrackerRow => 'pick_id' in x;

const NO_SLOT = Number.MAX_SAFE_INTEGER;

/** When a scheduled clip goes out (ISO): its live posts' first slot (else its posts'), as the character pipeline reads it; null with no slot. */
export function slotTime(c: Pick<LibraryClip, 'posts'>): string | null {
  const live = c.posts.filter((p) => p.status === 'scheduled' || p.status === 'posting');
  const slots = (live.length ? live : c.posts).filter((p) => !Number.isNaN(Date.parse(p.scheduled_for)));
  if (!slots.length) return null;
  return slots.reduce((a, b) => (Date.parse(b.scheduled_for) < Date.parse(a.scheduled_for) ? b : a)).scheduled_for;
}

/** Where a clip goes out: its posts' platforms, else the clip's own list; sorted (instagram, tiktok). */
export function clipPlatforms(c: Pick<LibraryClip, 'posts' | 'platforms'>): string[] {
  const fromPosts = [...new Set<string>(c.posts.map((p) => p.platform))];
  return (fromPosts.length ? fromPosts : [...c.platforms]).sort();
}

/** The slot as a sort key: a clip without one sorts last. */
const slotOf = (c: Pick<LibraryClip, 'posts'>): number => {
  const at = slotTime(c);
  return at ? Date.parse(at) : NO_SLOT;
};

/**
 * The Videos page's two groups. Making: the tracker rows whose chip is Making, then the library clips in production that no
 * row already owns (a clip is listed once, by its row, whatever the row's chip: a failed drop's half-made clip is not listed here),
 * the newest clip first. Scheduled: the approved and scheduled library
 * clips, the soonest slot first, a clip without a slot last.
 */
export function videoGroups(data: Snapshot): { making: (TrackerRow | LibraryClip)[]; scheduled: LibraryClip[] } {
  const rows = data.tracker.filter((r) => clipChip(r) === 'making');
  // every row owns its clip, whatever its chip: a failed drop with a half-made clip stays on the Clips page, not here as a bare clip
  const listed = new Set(data.tracker.map((r) => r.clip_id).filter((id): id is string => id != null));
  const clips = data.library
    .filter((c) => IN_PRODUCTION_STATES.includes(c.state) && !listed.has(c.id))
    .sort((a, b) => (Date.parse(b.created_at) || 0) - (Date.parse(a.created_at) || 0) || a.id.localeCompare(b.id));
  const scheduled = data.library
    .filter((c) => c.state === 'scheduled' || c.state === 'approved')
    .sort((a, b) => slotOf(a) - slotOf(b) || a.id.localeCompare(b.id));
  return { making: [...rows, ...clips], scheduled };
}
