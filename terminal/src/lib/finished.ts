// "Finished clips" on In the works (owner 2026-10-06): every clip that is made, waiting for the owner's OK, approved, scheduled or
// posted, watchable on the page with the Queue's player. Approving and rejecting stay in the Queue. Pure functions over the
// Library's rows (v_library); no browser.
import type { ClipState, LibraryClip } from './types';

export const FINISHED_STATES = ['awaiting_approval', 'approved', 'scheduled', 'posted'] as const satisfies ReadonlyArray<ClipState>;
export type FinishedState = (typeof FINISHED_STATES)[number];

/** The words of the tracker's steps: Your OK (step 6), then Scheduled and Posted. */
export const FINISHED_LABEL: Record<FinishedState, string> = {
  awaiting_approval: 'Your OK', approved: 'Approved', scheduled: 'Scheduled', posted: 'Posted',
};
/** The Library's tag tones: the owner's turn in amber, a live post in ice. */
export const FINISHED_TONE: Record<FinishedState, string> = { awaiting_approval: 'action', approved: '', scheduled: '', posted: 'live' };

/** How many players the section shows before "Show all" (each one signs a URL for its video). */
export const FINISHED_PAGE = 12;

const RANK: Record<FinishedState, number> = { awaiting_approval: 0, approved: 1, scheduled: 1, posted: 2 };

export const isFinished = (c: Pick<LibraryClip, 'state'>): c is Pick<LibraryClip, 'state'> & { state: FinishedState } =>
  (FINISHED_STATES as ReadonlyArray<string>).includes(c.state);

/** The finished clips: the owner's OK first, then approved and scheduled, then posted; the newest first within each. */
export function finishedClips<C extends Pick<LibraryClip, 'id' | 'state' | 'created_at' | 'posted_at'>>(library: ReadonlyArray<C>): C[] {
  const at = (c: C) => Date.parse(c.posted_at ?? c.created_at) || 0;
  return library
    .filter((c) => isFinished(c))
    .sort((a, b) => RANK[a.state as FinishedState] - RANK[b.state as FinishedState] || at(b) - at(a) || a.id.localeCompare(b.id));
}
