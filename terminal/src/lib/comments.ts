// "Comments to post today" (owner 2026-10-28): the comments the daily run drafts for the owner to post BY HAND from each character's
// own Instagram account (`studio engage save`, runs of kind comment_drafts; one row per London day, no migration). The studio never posts
// a comment itself. details = {day: 'YYYY-MM-DD', drafts: [{character, handle, post_url, comment}]}. Pure functions, no browser.
import { nameOf, orderRoster } from './roster';

/** One comment to post: where (the account and its post) and what to write. */
export interface CommentDraft {
  /** The character who posts it (his slug). */
  character: string;
  /** The account being commented on, with its @. */
  handle: string;
  /** The post to open: an https Instagram link. */
  postUrl: string;
  comment: string;
}

/** One London day's drafts. */
export interface CommentDay {
  /** The London day, YYYY-MM-DD. */
  day: string;
  drafts: CommentDraft[];
}

export interface CommentGroup {
  slug: string;
  name: string;
  drafts: CommentDraft[];
}

const isDay = (v: unknown): v is string => typeof v === 'string' && /^\d{4}-\d{2}-\d{2}$/.test(v) && !Number.isNaN(Date.parse(`${v}T12:00:00Z`));
const text = (v: unknown): string | null => (typeof v === 'string' && v.trim() ? v.trim() : null);

/** Only an https link on instagram.com is ever opened from here (a stored value is data: no other scheme or host becomes a link). */
export function isPostUrl(v: string): boolean {
  try {
    const u = new URL(v);
    return u.protocol === 'https:' && (u.hostname === 'instagram.com' || u.hostname.endsWith('.instagram.com'));
  } catch {
    return false;
  }
}

/** A handle without case, spaces or the @: how two drafts for one account are told apart. */
const handleKey = (h: string): string => h.trim().replace(/^@/, '').toLowerCase();

function readDraft(raw: unknown): CommentDraft | null {
  if (!raw || typeof raw !== 'object') return null;
  const { character, handle, post_url, comment } = raw as Record<string, unknown>;
  const c = text(character);
  const h = text(handle);
  const u = text(post_url);
  const t = text(comment);
  if (!c || !h || !u || !t || !handleKey(h) || !isPostUrl(u)) return null;
  return { character: c, handle: h.startsWith('@') ? h : `@${h}`, postUrl: u, comment: t };
}

/**
 * The days in the `comment_drafts` runs (`details.day`, `details.drafts`), oldest first. A run with no usable day or no usable draft is
 * skipped; a draft with a missing field, or a post link that is not an https Instagram link, is left out (there would be nothing to
 * open). Two runs of one day join (the job keeps one row per day; this only keeps a stray second row harmless), and one account is
 * listed once per character, the later row winning.
 */
export function parseCommentDays(rows: ReadonlyArray<{ details?: unknown } | null | undefined>): CommentDay[] {
  const byDay = new Map<string, Map<string, CommentDraft>>();
  for (const r of rows) {
    const d = r?.details;
    if (!d || typeof d !== 'object') continue;
    const { day, drafts } = d as { day?: unknown; drafts?: unknown };
    if (!isDay(day) || !Array.isArray(drafts)) continue;
    const held = byDay.get(day) ?? new Map<string, CommentDraft>();
    for (const raw of drafts) {
      const draft = readDraft(raw);
      if (draft) held.set(`${draft.character}|${handleKey(draft.handle)}`, draft);
    }
    if (held.size) byDay.set(day, held);
  }
  return [...byDay.keys()].sort().map((day) => ({ day, drafts: [...byDay.get(day)!.values()] }));
}

/** The drafts of one London day (`dayKey` as `londonDayKey` gives it); none when the day has no row. */
export const draftsForDay = (days: ReadonlyArray<CommentDay> | null | undefined, dayKey: string): CommentDraft[] =>
  (days ?? []).filter((d) => d.day === dayKey).flatMap((d) => d.drafts);

/** The drafts grouped by character in the owner's order (Franz, Reginald, Lenny, then any other, a paused one last), each group in the
 * order the run wrote them. The name is the loaded character's, else the slug in words. */
export function groupDrafts(
  drafts: ReadonlyArray<CommentDraft>,
  characters: ReadonlyArray<{ slug: string; name: string; status?: string | null }> = [],
): CommentGroup[] {
  const known = new Map(characters.map((c) => [c.slug, c]));
  const slugs = [...new Set(drafts.map((d) => d.character))];
  return orderRoster(slugs.map((slug) => known.get(slug) ?? { slug, name: nameOf(slug), status: null })).map((c) => ({
    slug: c.slug,
    name: c.name,
    drafts: drafts.filter((d) => d.character === c.slug),
  }));
}
