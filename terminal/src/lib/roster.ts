// The character roster as the terminal knows it (owner 2026-10-06): Franz, Reginald, Lenny Gold; Biscuit is retired (`paused`,
// kept for his history); the Borat-type joins once he is named (`characters/<slug>/`). The database (v_characters) is the truth:
// these are only the owner's order, the names and liveries of the known slugs, and the fallback while nothing has loaded. A slug
// the terminal has never heard of still works everywhere: a title-cased name, a three-letter code and the neutral livery.

export interface RosterEntry {
  slug: string;
  name: string;
}

/** The roster in the owner's order: what the pickers offer before the studio has loaded its characters. */
export const ROSTER: ReadonlyArray<RosterEntry> = [
  { slug: 'franz', name: 'Franz' },
  { slug: 'reginald', name: 'Reginald' },
  { slug: 'lenny', name: 'Lenny Gold' },
];

const NAMES: Readonly<Record<string, string>> = { franz: 'Franz', reginald: 'Reginald', lenny: 'Lenny Gold', biscuit: 'Biscuit' };

/** The slugs styles.css gives a livery colour (`.livery.<slug>`, `.pick-sec.<slug>`, ...); any other is `none`. */
const LIVERIES: ReadonlySet<string> = new Set(['franz', 'reginald', 'lenny', 'biscuit']);

/** A character's name: the known one, else the slug in words ("borat-type" -> "Borat Type"). */
export function nameOf(slug: string): string {
  if (NAMES[slug]) return NAMES[slug];
  const words = slug.split(/[-_\s]+/).filter(Boolean);
  return words.length ? words.map((w) => w.charAt(0).toUpperCase() + w.slice(1)).join(' ') : slug;
}

/** The CSS class of a character's livery: its slug when styles.css has one, else `none` (the neutral plate). */
export const liveryClass = (slug: string | null | undefined): string => (slug && LIVERIES.has(slug) ? slug : 'none');

/** A retired or not-yet-running character: kept in history and filters, never offered for a new video. */
export const isPaused = (c: { status?: string | null }): boolean => c.status === 'paused';

/** The owner's order: the roster first (Franz, Reginald, Lenny), then any other character by slug, a paused one last. */
export function orderRoster<T extends { slug: string; status?: string | null }>(list: ReadonlyArray<T>): T[] {
  const rank = (slug: string) => {
    const i = ROSTER.findIndex((r) => r.slug === slug);
    return i < 0 ? ROSTER.length : i;
  };
  return [...list].sort(
    (a, b) => Number(isPaused(a)) - Number(isPaused(b)) || rank(a.slug) - rank(b.slug) || a.slug.localeCompare(b.slug),
  );
}

/**
 * Who a new video can be made with: every loaded character that is not paused, in the owner's order (the roster while
 * nothing has loaded). Biscuit is retired: he keeps his history but takes no new drops or picks.
 */
export function activeRoster(characters: ReadonlyArray<{ slug: string; name: string; status?: string | null }> | null | undefined): RosterEntry[] {
  const list = characters?.length ? orderRoster(characters).filter((c) => !isPaused(c)) : ROSTER;
  return list.map((c) => ({ slug: c.slug, name: c.name }));
}
