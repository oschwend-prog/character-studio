// Terminal v2, Clips page (owner 2026-10-07): one plain chip per dropped clip instead of the 8-step stepper, and the filters over
// them. Pure functions over v_tracker rows (drop_card, migrations 0012-0013); no browser.
import { canChooseCharacter, dropActions, dropCredits, type DropAction } from './drop';
import { FINISHED_STATES } from './finished';
import type { RosterEntry } from './roster';
import { IN_PRODUCTION_STATES } from './rules';
import type { DropState, TrackerRow } from './types';

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
 * 4. Adding (uploading, the file not saved yet), Checking (checking, waiting, and an upload whose file is saved: the owner's clips
 *    folder attaches it before the check is requested), then Ready only when the owner chose the character (character_by
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
      return row.owner_clip_path ? 'checking' : 'adding'; // the file is saved (the clips folder): only its check is still to come
    case 'ready':
      return d.character_by === 'owner' ? 'ready' : 'pick';
    default:
      return 'checking'; // checking, waiting, or a row with no card
  }
}

/**
 * The free one-tap confirmation of a Pick a character clip: "Use <him>" records the character the row shows as the owner's own
 * (set_drop_character with the same one), which turns the chip to Ready without a new check or a credit. Offered exactly when the
 * chip is Pick a character, the character can still be chosen and is still on offer (a paused one is refused: the menu does the
 * choosing then); null otherwise. The native menu cannot do it: it shows this character already, so choosing it fires nothing.
 */
export function characterConfirm(row: TrackerRow, roster: ReadonlyArray<RosterEntry>): { slug: string; name: string } | null {
  if (clipChip(row) !== 'pick' || !canChooseCharacter(row)) return null;
  const live = roster.find((c) => c.slug === row.character_slug);
  return live ? { slug: live.slug, name: live.name } : null;
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

/** The Clips page's filter row, in order, with the owner's words (the same words as the chips). */
export const CLIP_FILTERS: ReadonlyArray<{ id: ClipFilter; label: string }> = [
  { id: 'all', label: 'All' },
  { id: 'pick', label: 'Pick a character' },
  { id: 'ready', label: 'Ready' },
  { id: 'making', label: 'Making' },
  { id: 'done', label: 'Done' },
  { id: 'problems', label: 'Blocked or failed' },
];

/** What the table says, in one line, when a filter shows no clip. */
export const CLIP_FILTER_EMPTY: Record<ClipFilter, string> = {
  all: 'No clips yet: add one above and it is checked for free.',
  pick: 'No clips wait for a character.',
  ready: 'No clip is ready to make.',
  making: 'Nothing is being made right now.',
  done: 'No clip is done yet.',
  problems: 'Nothing is blocked or failed.',
};

/** The filter an address asks for (`?f=ready`, the query of the hash); an unknown or missing value is All. */
export function parseClipFilter(query: string): ClipFilter {
  const f = new URLSearchParams(query).get('f');
  return CLIP_FILTERS.find((o) => o.id === f)?.id ?? 'all';
}

/** The query with the filter set (All removes it, a clean address), every other key of the query kept as it was. */
export function clipFilterQuery(query: string, f: ClipFilter): string {
  const q = new URLSearchParams(query);
  if (f === 'all') q.delete('f');
  else q.set('f', f);
  return q.toString();
}

/** The `.drop-state` look of each chip: the table keeps its colours (amber Ready, ice for what moves, red for Blocked and Failed). */
export const CHIP_CLASS: Record<ClipChip, DropState> = {
  adding: 'uploading',
  checking: 'checking',
  pick: 'ready',
  ready: 'ready',
  making: 'making',
  done: 'made',
  blocked: 'blocked',
  failed: 'failed',
};

/** The buttons that spend credits (Make it, and Try again after a failed Make it). */
const PAID_ACTIONS: ReadonlyArray<DropAction> = ['make', 'adjust', 'retry-make'];

/**
 * The buttons a clip's row offers: the drop card's (dropActions), but never a paid one next to a Making or Done chip. The drop
 * card can lag behind its clip (Make it was tapped, or the clip exists, and the card still says ready), and a second Make it on
 * a clip that is on its way would spend twice.
 */
export function clipActions(row: TrackerRow, now: number): DropAction[] {
  const d = row.drop_card;
  if (!d) return [];
  const actions = dropActions(d, now, Boolean(row.owner_clip_path));
  const chip = clipChip(row);
  return chip === 'making' || chip === 'done' ? actions.filter((a) => !PAID_ACTIONS.includes(a)) : actions;
}

/** When a clip was dropped: the card's own time, else when the pick was approved; null when neither is a valid time. */
export function droppedAt(r: Pick<TrackerRow, 'drop_card' | 'approved_at'>): number | null {
  for (const iso of [r.drop_card?.at, r.approved_at]) {
    const t = iso ? Date.parse(iso) : NaN;
    if (Number.isFinite(t)) return t;
  }
  return null;
}

/**
 * The Clips page's order (spec B.2): the newest drop first, whatever its state (the filters carry the grouping). A clip with no
 * valid time comes last; equal times fall back to the pick id, so the order never jumps between renders. Returns a new list.
 */
export function newestFirst<R extends Pick<TrackerRow, 'pick_id' | 'drop_card' | 'approved_at'>>(rows: ReadonlyArray<R>): R[] {
  const at = (r: R) => droppedAt(r) ?? Number.NEGATIVE_INFINITY;
  return [...rows].sort((a, b) => {
    const [x, y] = [at(a), at(b)];
    return (x === y ? 0 : y > x ? 1 : -1) || a.pick_id.localeCompare(b.pick_id);
  });
}

/**
 * The header line's numbers: the clips the owner can Make now (their row offers Make it, so a Ready and a Pick a character clip,
 * never one that is Making or Done) and what making them all costs, each at the price its row shows (its own Adjust included).
 */
export function makeTotal(rows: ReadonlyArray<TrackerRow>, now: number): { count: number; credits: number } {
  const makeable = rows.filter((r) => clipActions(r, now).includes('make'));
  return { count: makeable.length, credits: makeable.reduce((sum, r) => sum + dropCredits(r.drop_card!, r.drop_card!.adjust ?? {}), 0) };
}
