// Terminal v3, Clips by character (spec section 6; owner 2026-10-07: "show per character what clips are a good choice, what needs
// approving, maybe rank them so it's easy for me to approve the top choices for rendering"): a section per live character with
// "Needs you" first, then his Ready clips ranked by score, then what is on its way and done, the blocked and failed folded into one
// line. The switch By character | All clips lives in the address (`#/clips?v=all`). Pure functions over v_tracker rows; no browser.
import { clipChip, clipFilterQuery, newestFirst, type ClipChip, type ClipFilter } from './clipstatus';
import { nameOf } from './roster';
import { familyOf, rankClips, scoreOf, topPicks } from './ranking';
import type { TrackerRow } from './types';

export type ClipsView = 'character' | 'all';

/** The view an address asks for: `v=all` is All clips, and so is any `f` filter (those exist only there: Today's old links,
 * `#/clips?f=problems`); anything else is By character, the default. */
export function parseClipsView(query: string): ClipsView {
  const q = new URLSearchParams(query);
  return q.get('v') === 'all' || q.has('f') ? 'all' : 'character';
}

/** The query for a view: All clips sets `v=all` (a filter stays); By character drops `v` and the filter (it has none), every
 * other key kept as it was. */
export function clipsViewQuery(query: string, view: ClipsView): string {
  const q = new URLSearchParams(query);
  if (view === 'all') q.set('v', 'all');
  else {
    q.delete('v');
    q.delete('f');
  }
  return q.toString();
}

/**
 * The query after a filter chip of All clips: the filter (clipFilterQuery: All removes it) and `v=all`, because a filter exists
 * only in All clips. Without `v=all`, the All chip on an old `#/clips?f=…` address would leave a bare `#/clips` that still shows
 * All clips, and the By character button (which asks for that same bare address) would do nothing.
 */
export function filterAddressQuery(query: string, f: ClipFilter): string {
  return clipsViewQuery(clipFilterQuery(query, f), 'all');
}

/** One live character's clips, as the By character view shows them. */
export interface CharacterClips {
  slug: string;
  name: string;
  /** Clips the studio filed under him that wait for the owner's character choice (the Pick a character chip), newest first. */
  needsYou: TrackerRow[];
  /** His Ready clips, ranked: scored first by score, then unscored newest first (rankClips). */
  ready: TrackerRow[];
  /** Being added, checked or made, newest first. */
  onTheWay: TrackerRow[];
  /** Done: the owner's OK or later, or made; newest first. */
  done: TrackerRow[];
  /** Blocked or failed: folded into one line; newest first. */
  problems: TrackerRow[];
}

/**
 * The By character sections: one per character in `characters` (the live ones, in the owner's order), from the rows with a drop
 * card. `others` are the dropped clips of no listed character (none chosen, or a paused one): All clips shows them.
 */
export function clipsByCharacter(
  rows: ReadonlyArray<TrackerRow>,
  characters: ReadonlyArray<{ slug: string; name: string }>,
): { groups: CharacterClips[]; others: TrackerRow[] } {
  const clips = rows.filter((r) => r.drop_card);
  const groups = characters.map((c) => {
    const his = clips.filter((r) => r.character_slug === c.slug);
    const by = (...chips: string[]) => his.filter((r) => chips.includes(clipChip(r)));
    return {
      slug: c.slug,
      name: c.name,
      needsYou: newestFirst(by('pick')),
      ready: rankClips(by('ready')),
      onTheWay: newestFirst(by('adding', 'checking', 'making')),
      done: newestFirst(by('done')),
      problems: newestFirst(by('blocked', 'failed')),
    };
  });
  const listed = new Set(characters.map((c) => c.slug));
  return { groups, others: clips.filter((r) => !r.character_slug || !listed.has(r.character_slug)) };
}

/** The Top pick badge (spec 6): one of the first three of his ranked Ready clips, and scored (an unscored clip is "not scored yet",
 * never a top pick by a score it does not have). `index` is the clip's place in the ranking, from 0. */
export function isTopPick(row: Pick<TrackerRow, 'drop_card'>, index: number): boolean {
  return index >= 0 && index < 3 && scoreOf(row) != null;
}

/** Where a version is, in the words of the versions line. */
export const VERSION_WORDS: Record<ClipChip, string> = {
  adding: 'being added',
  checking: 'being checked',
  pick: 'waits for your choice',
  ready: 'ready',
  making: 'being made',
  done: 'done',
  blocked: 'blocked',
  failed: 'failed',
};

/**
 * The clip's other versions in one line (spec 6): "Also: Lenny Gold, ready" or "Also: Reginald, done; Franz, being checked"; the root
 * and the versions in their family order, skipped ones left out; null for a clip with no other version among `rows`. `names` gives a
 * character's name (the loaded characters), else the roster's.
 */
export function versionsLine(row: TrackerRow, rows: ReadonlyArray<TrackerRow>, names: ReadonlyMap<string, string> = new Map()): string | null {
  const others = familyOf(row, rows).filter((m) => m.pick_id !== row.pick_id);
  if (!others.length) return null;
  const name = (slug: string | null) => (slug ? names.get(slug) ?? nameOf(slug) : 'no character');
  return `Also: ${others.map((m) => `${name(m.character_slug)}, ${VERSION_WORDS[clipChip(m)]}`).join('; ')}`;
}

/** The folded line of the blocked and failed clips: "1 clip can't be used: see why", "3 clips can't be used: see why". */
export function cantUseLine(n: number): string {
  return `${n} ${n === 1 ? 'clip' : 'clips'} can’t be used: see why`;
}

/** The clips that wait for his character choice, said next to Ready and never inside it: "+2 need your choice", "+1 needs your
 * choice"; "" for none. One meaning of Ready on every screen (controller ruling 2026-10-08): Ready is the Ready chip only. */
export function needYourChoice(n: number): string {
  return n > 0 ? `+${n} ${n === 1 ? 'needs' : 'need'} your choice` : '';
}

/** "4 ready", "4 ready +2 need your choice", "0 ready +1 needs your choice". */
export function readyWithChoice(ready: number, needs: number): string {
  return [`${ready} ready`, needYourChoice(needs)].filter(Boolean).join(' ');
}

/**
 * Today's Make these: the clips it shows, each live character's top 3 Ready clips (topPicks). Only these can be ticked there, so a
 * ticked clip never drops out of view while it stays in the bar.
 */
export function makeTheseIds(rows: ReadonlyArray<TrackerRow>, characters: ReadonlyArray<{ slug: string; name: string }>): Set<string> {
  return new Set(clipsByCharacter(rows, characters).groups.flatMap((g) => topPicks(g.ready, 3).map((r) => r.pick_id)));
}

/** His section's one line of counts: "4 ready +2 need your choice · 1 on its way"; "nothing yet" for a character with no clip. */
export function sectionSummary(g: CharacterClips): string {
  const parts = [
    g.ready.length || g.needsYou.length ? readyWithChoice(g.ready.length, g.needsYou.length) : '',
    g.onTheWay.length ? `${g.onTheWay.length} on ${g.onTheWay.length === 1 ? 'its' : 'their'} way` : '',
    g.done.length ? `${g.done.length} done` : '',
  ].filter(Boolean);
  return parts.length ? parts.join(' · ') : g.problems.length ? 'nothing usable yet' : 'nothing yet';
}
