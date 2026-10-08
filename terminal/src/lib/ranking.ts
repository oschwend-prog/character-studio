// Terminal v3 (spec sections 4-6, owner 2026-10-07): the saved clips ranked by their score so the top choices are easy to make,
// one clip used for up to three characters, and the "Make N selected" bar. Pure functions over v_tracker rows (drop_card.score and
// drop_card.copy_of, migration 0015) and the characters (v_characters); makeMany only calls the backend's request_job. No browser.
// The reuse rules mirror studio.copy_drop (migration 0015) and studio.drop.copy_drop: the database refuses anything else anyway.
import { clipChip, droppedAt } from './clipstatus';
import { dropCredits } from './drop';
import { isPaused, orderRoster, type RosterEntry } from './roster';
import type { Backend, Character, DropAdjust, DropState, TrackerRow } from './types';

/** A clip goes to at most this many characters: the root and two versions (studio.drop.MAX_FAMILY). */
export const MAX_FAMILY = 3;

/**
 * The clip's score total (0-100), or null when it has none: a clip checked before the score existed, a blocked or failed check,
 * or a score that is not a finite number. Never NaN, never 0 for "no score" (Review Focus 3).
 */
export function scoreOf(r: Pick<TrackerRow, 'drop_card'>): number | null {
  const s = r.drop_card?.score as unknown;
  if (!s || typeof s !== 'object') return null;
  const total = (s as { total?: unknown }).total;
  return typeof total === 'number' && Number.isFinite(total) ? total : null;
}

type Ranked = Pick<TrackerRow, 'pick_id' | 'drop_card' | 'approved_at'>;

/**
 * The ranking (spec sections 5.2 and 6): the scored clips first, highest score first; then the unscored ones (checked before the
 * score existed), newest first. A tie on the score goes to the newest clip; equal times to the pick id, so the order never jumps
 * between renders. A clip with no valid time is the oldest. Sorts only: the caller chooses which rows. Returns a new list.
 */
export function rankClips<R extends Ranked>(rows: ReadonlyArray<R>): R[] {
  const at = (r: R) => droppedAt(r) ?? Number.NEGATIVE_INFINITY;
  return [...rows].sort((a, b) => {
    const [sa, sb] = [scoreOf(a), scoreOf(b)];
    if ((sa == null) !== (sb == null)) return sa == null ? 1 : -1;
    if (sa != null && sb != null && sa !== sb) return sb - sa;
    const [ta, tb] = [at(a), at(b)];
    return (ta === tb ? 0 : tb > ta ? 1 : -1) || a.pick_id.localeCompare(b.pick_id);
  });
}

/**
 * The top picks (spec 5.2 "Make these" and the Top pick badge of 6): the best `n` Ready clips, ranked. Ready is the Clips page's
 * Ready chip: checked, the owner's own character, nothing on its way yet. A clip whose character the studio chose is "Needs you"
 * (one tap confirms it), never a top pick: Make it would be paid for a character he never chose. Give it one character's rows.
 */
export function topPicks(rows: ReadonlyArray<TrackerRow>, n = 3): TrackerRow[] {
  return rankClips(rows.filter((r) => clipChip(r) === 'ready')).slice(0, Math.max(0, n));
}

// ---- reuse: one clip, up to three characters (spec section 4) --------------------------------------------------------------------

/** The pick id of a drop's family root: its `copy_of` when that is a non-empty string, else the pick itself (studio.family_root_id). */
export function familyRootId(r: Pick<TrackerRow, 'pick_id' | 'drop_card'>): string {
  const c = r.drop_card?.copy_of;
  return typeof c === 'string' && c !== '' ? c : r.pick_id;
}

/**
 * A drop's family among `rows`: the root and its versions, a skipped pick left out (it does not count, studio.copy_drop), the
 * root first, then the versions oldest first. `row` itself counts even when `rows` lacks it. [] for a row with no drop card.
 */
export function familyOf<R extends Pick<TrackerRow, 'pick_id' | 'drop_card' | 'status' | 'approved_at'>>(row: R, rows: ReadonlyArray<R>): R[] {
  if (!row.drop_card) return [];
  const root = familyRootId(row);
  const seen = new Set<string>();
  const members = [row, ...rows].filter((r) => {
    if (seen.has(r.pick_id) || !r.drop_card || r.status === 'skipped' || familyRootId(r) !== root) return false;
    seen.add(r.pick_id);
    return true;
  });
  const at = (r: R) => droppedAt(r) ?? Number.POSITIVE_INFINITY;
  return members.sort((a, b) => Number(b.pick_id === root) - Number(a.pick_id === root) || at(a) - at(b) || a.pick_id.localeCompare(b.pick_id));
}

/** The states a root must be in before a version can be filed: its check finished (studio.copy_drop). */
const CHECKED: ReadonlyArray<DropState> = ['ready', 'making', 'made'];

type Candidate = Pick<Character, 'slug' | 'name' | 'status' | 'bodies' | 'setup'>;

/**
 * "Use for another character" (spec section 4): the characters this clip may also go to, in the owner's order. Like
 * studio.copy_drop, from the root's card (a version is asked about its root): nothing unless the root is among `rows` and its
 * check finished (ready, making or made) and the family has fewer than 3 members (skipped ones not counted); then every
 * character not paused and not already in the family (his own included) whose kinds of star (setup.stars, else setup.swap.stars)
 * include the root star's kind, and whose bodies include its body. A character with no stars list is judged by his body alone,
 * as the SQL does; a clip with no clear star (none, or no star at all) goes to nobody. `rows` may be the family or every row.
 */
export function reuseTargets(row: TrackerRow, roster: ReadonlyArray<Candidate>, rows: ReadonlyArray<TrackerRow>): RosterEntry[] {
  const family = familyOf(row, rows);
  const root = family.find((r) => r.pick_id === familyRootId(row));
  const d = root?.drop_card;
  if (!d || !CHECKED.includes(d.state) || family.length >= MAX_FAMILY) return [];
  const kind = d.star?.kind;
  const body = d.star?.body;
  if (!kind || kind === 'none' || !body) return [];
  const taken = new Set(family.map((r) => r.character_slug));
  return orderRoster(roster)
    .filter((c) => {
      if (taken.has(c.slug) || isPaused(c)) return false;
      const stars = c.setup?.stars ?? c.setup?.swap?.stars;
      if (Array.isArray(stars) && !stars.includes(kind)) return false;
      return (c.bodies ?? []).includes(body);
    })
    .map((c) => ({ slug: c.slug, name: c.name }));
}

// ---- the selection bar: "Make 3 selected · 291 credits" (spec section 5.2) ---------------------------------------------------------

/**
 * What the ticked clips cost: each at the price its row shows (its own Adjust included, as the drops table prices it), each clip
 * once, only clips with a price (checked). `count` is how many of the ticked ids that is.
 */
export function selectionTotal(rows: ReadonlyArray<Pick<TrackerRow, 'pick_id' | 'drop_card'>>, ids: ReadonlyArray<string>): { count: number; credits: number } {
  const wanted = new Set(ids);
  const priced = rows.filter((r, i) => wanted.has(r.pick_id) && r.drop_card?.credits != null && rows.findIndex((x) => x.pick_id === r.pick_id) === i);
  return { count: priced.length, credits: priced.reduce((sum, r) => sum + dropCredits(r.drop_card!, r.drop_card!.adjust ?? {}), 0) };
}

/** What happened to one clip of "Make N selected". */
export interface MakeResult {
  pickId: string;
  ok: boolean;
  /** The cloud job started now (true), or the next run starts it (false); false on a refusal. */
  dispatched: boolean;
  /** One plain line: what was done, or the database's own refusal. */
  message: string;
}

/**
 * "Make N selected" after the owner's confirm (the confirm is the screen's, never here): request_job(pick, 'make') for each clip,
 * one at a time, in the order given, each clip once. A refusal is that clip's own result and the next clip is still asked (Review
 * Focus 5: one failure never hides the others). `adjustOf` gives the Adjust a clip's price was shown for (its stored one), null =
 * the check's own choices.
 */
export async function makeMany(
  backend: Pick<Backend, 'requestJob'>,
  pickIds: ReadonlyArray<string>,
  adjustOf: (pickId: string) => DropAdjust | null = () => null,
): Promise<MakeResult[]> {
  const results: MakeResult[] = [];
  for (const pickId of [...new Set(pickIds)]) {
    try {
      const { dispatched } = await backend.requestJob(pickId, 'make', adjustOf(pickId));
      results.push({ pickId, ok: true, dispatched, message: dispatched ? 'Sent: making starts now' : 'Sent: the next run starts it' });
    } catch (e) {
      results.push({ pickId, ok: false, dispatched: false, message: e instanceof Error ? e.message : String(e) });
    }
  }
  return results;
}

/** The bar's one line after it ran: "3 clips sent to be made", "2 clips sent to be made, 1 refused: <why>", "Nothing was sent". */
export function makeSummary(results: ReadonlyArray<MakeResult>): string {
  const sent = results.filter((r) => r.ok).length;
  const refused = results.filter((r) => !r.ok);
  const head = sent === 0 ? 'Nothing was sent' : sent === 1 ? '1 clip sent to be made' : `${sent} clips sent to be made`;
  return refused.length ? `${head}, ${refused.length} refused: ${refused[0].message}` : head;
}
