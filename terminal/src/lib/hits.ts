// Terminal v3, the cloud hits job in the terminal (spec section 10; owner 2026-10-07: "set up the scrapecreators cloud job", "don't
// skip cool viral up-and-coming clips because you think they don't fit a character"). The daily job (studio-hits.yml, 06:30 London)
// keeps the top TikTok and Instagram posts of our niches in studio.hits; the terminal reads the new ones of the last 14 days
// (v_hits, migration 0016) and shows them on Clips › By character: "Hot right now" (the general lane, top 10, any character may
// take one) above the sections, and in each character's section "Worth saving" (his top 5). Each hit: Open (the post, to watch
// it), "Use this clip" (add_drop of its link for that character, then set_hit_status dropped: the cloud drop job fetches that one
// post and checks it for free) and "Not for us" (dismissed). Also here: where the clip card's Keep toggle shows (retention,
// set_drop_keep). Pure functions; fileHit only calls the backend.
import { formatViews } from './format';
import { canonicalVideoUrl } from './rules';
import { isPaused, orderRoster, type RosterEntry } from './roster';
import type { Backend, Character, Hit, HitStatus, TrackerRow } from './types';

/** A hit is offered for this many days after it was posted (v_hits; studio.hits.MAX_AGE_DAYS). */
export const HIT_DAYS = 14;
const DAY = 86_400_000;
const HOUR = 3_600_000;

/** The lane of a hit: the character it was searched for, or `general` (no character). */
export const laneOf = (h: Pick<Hit, 'character_slug'>): string => h.character_slug ?? 'general';

const isNew = (h: Pick<Hit, 'status'>) => (h.status ?? 'new') === 'new';
const at = (iso: string | null | undefined) => {
  const t = iso ? Date.parse(iso) : Number.NaN;
  return Number.isFinite(t) ? t : null;
};

/** Best first (v_hits' order): the score, then the latest seen, then the id, so the order never jumps between loads. */
function bestFirst(a: Hit, b: Hit): number {
  if (a.score !== b.score) return b.score - a.score;
  const [la, lb] = [at(a.last_seen) ?? 0, at(b.last_seen) ?? 0];
  return lb - la || a.hit_id.localeCompare(b.hit_id);
}

/**
 * What v_hits lists (the demo's copy of the view): the new hits posted in the last 14 days or with no known date, best first. A
 * hit weeks old is never offered, whatever its stored score.
 */
export function offeredHits(hits: ReadonlyArray<Hit>, now: number): Hit[] {
  return hits
    .filter((h) => {
      const t = at(h.posted_at);
      return isNew(h) && (h.posted_at == null || (t != null && t > now - HIT_DAYS * DAY));
    })
    .sort(bestFirst);
}

/** "Worth saving" (spec 10): his top `n` new hits, best score first. */
export function worthSaving(hits: ReadonlyArray<Hit>, slug: string, n = 5): Hit[] {
  return hits.filter((h) => h.character_slug === slug && isNew(h)).sort(bestFirst).slice(0, Math.max(0, n));
}

/** "Hot right now" (spec 10): the general lane's top `n` new hits (no character: any character may take one), best first. */
export function hotNow(hits: ReadonlyArray<Hit>, n = 10): Hit[] {
  return hits.filter((h) => h.character_slug == null && isNew(h)).sort(bestFirst).slice(0, Math.max(0, n));
}

// ---- the lines on a hit card ----------------------------------------------------------------------------------------------------

const intGB = new Intl.NumberFormat('en-GB', { maximumFractionDigits: 0 });

/** The reach (views ÷ the creator's followers) for a glance: "12× his followers", "2.5× his followers"; null without it. */
export function reachLabel(reach: number | null | undefined): string | null {
  if (typeof reach !== 'number' || !Number.isFinite(reach) || reach < 0) return null;
  let x: string;
  if (reach < 0.1) return 'under 0.1× his followers';
  if (reach >= 10) x = intGB.format(Math.round(reach));
  else x = String(Number(reach.toFixed(1)));
  return `${x}× his followers`;
}

/** When it was posted: "just now", "5 hours ago", "1 day ago", "2 days ago"; "posting date unknown" without a date. */
export function postedLabel(postedAt: string | null | undefined, now: number): string {
  const t = at(postedAt);
  if (t == null) return 'posting date unknown';
  const ms = now - t;
  if (ms < HOUR) return 'just now';
  if (ms < DAY) {
    const h = Math.floor(ms / HOUR);
    return `${h} ${h === 1 ? 'hour' : 'hours'} ago`;
  }
  const d = Math.floor(ms / DAY);
  return `${d} ${d === 1 ? 'day' : 'days'} ago`;
}

/** The card's numbers: the views (or the likes when the platform gave no play count: Instagram's search), the reach, posted. */
export function hitNumbers(h: Hit, now: number): string[] {
  const seen = h.views != null ? `${formatViews(h.views)} views` : h.likes != null ? `${formatViews(h.likes)} likes` : null;
  return [seen, reachLabel(h.reach), postedLabel(h.posted_at, now)].filter((x): x is string => Boolean(x));
}

/**
 * Why it is worth saving, in one line (the hit-pattern rules 2-3: reach over raw views, fresh over old): "Rising fast" (3× its
 * creator's followers or more within 3 days), "Spreading far past the creator’s fans" (3× or more), "Brand new" (under a day),
 * "Over a million views"; then what it was found for (the keyword) or "on the trending feed" (no keyword).
 */
export function hitWhy(h: Hit, now: number): string {
  const t = at(h.posted_at);
  const age = t == null ? null : now - t;
  const reach = typeof h.reach === 'number' && Number.isFinite(h.reach) ? h.reach : null;
  let cue: string | null = null;
  if (reach != null && reach >= 3 && age != null && age <= 3 * DAY) cue = 'Rising fast';
  else if (reach != null && reach >= 3) cue = 'Spreading far past the creator’s fans';
  else if (age != null && age < DAY) cue = 'Brand new';
  else if ((h.views ?? 0) >= 1_000_000) cue = 'Over a million views';
  const keyword = h.keyword?.trim();
  const source = keyword ? `found for “${keyword}”` : 'on the trending feed';
  return cue ? `${cue} · ${source}` : source.charAt(0).toUpperCase() + source.slice(1);
}

const PLATFORM: Record<string, string> = { tiktok: 'TikTok', instagram: 'Instagram' };

/** What the card is called: the caption's first line (at most 120 characters), else "@handle on TikTok", else "A TikTok video". */
export function hitTitle(h: Pick<Hit, 'caption' | 'creator_handle' | 'platform'>): string {
  const line = (h.caption ?? '').split('\n').map((s) => s.trim()).find(Boolean);
  if (line) return line.length > 120 ? `${line.slice(0, 119).trimEnd()}…` : line;
  const where = PLATFORM[h.platform] ?? h.platform;
  return h.creator_handle ? `${h.creator_handle} on ${where}` : `A ${where} video`;
}

/** The post's link for Open (a new tab): only an https link is ever opened; anything else is null (no Open button). */
export function postLink(url: string | null | undefined): string | null {
  if (typeof url !== 'string' || !url.trim() || /\s/.test(url.trim())) return null;
  try {
    const u = new URL(url.trim());
    return u.protocol === 'https:' && u.hostname ? u.href : null;
  } catch {
    return null;
  }
}

// ---- who may take a general hit -------------------------------------------------------------------------------------------------

/** A keyword that names a dog (whole words): the hit's star is a dog. "hotdog" is no dog. */
const DOG = /\b(dogs?|pupp(y|ies)|pups?|doggos?|dachshunds?|sausage dogs?|corgis?|pooch(es)?)\b/i;

/**
 * "Use this clip" on a general hit (spec 10: any character may take it): the live characters who could take its star, in the
 * owner's order. A hit says nothing about its star except what it was found for: a keyword naming a dog gives the reuse rules of
 * spec 4 for a dog (his kinds of star, setup.stars else setup.swap.stars, include a dog, and he has a quadruped body; with no
 * stars list his body alone decides, as copy_drop does); any other hit goes to every live character (the free check blocks a
 * wrong star anyway). A paused or designing character takes none.
 */
export function hitTakers(h: Pick<Hit, 'keyword'>, roster: ReadonlyArray<Pick<Character, 'slug' | 'name' | 'status' | 'bodies' | 'setup'>>): RosterEntry[] {
  const dog = DOG.test(h.keyword ?? '');
  return orderRoster(roster)
    .filter((c) => {
      if (c.status !== 'live' || isPaused(c)) return false;
      if (!dog) return true;
      const stars = c.setup?.stars ?? c.setup?.swap?.stars;
      if (Array.isArray(stars) && !stars.includes('dog')) return false;
      return (c.bodies ?? []).includes('quadruped');
    })
    .map((c) => ({ slug: c.slug, name: c.name }));
}

// ---- "Use this clip" --------------------------------------------------------------------------------------------------------------

/** What "Use this clip" did: the drop filed (or found again: `duplicate`), and whether the hit was marked dropped. */
export interface FiledHit {
  pickId: string;
  duplicate: boolean;
  marked: boolean;
  /** Why the hit could not be marked (the clip is filed all the same); null when it was. */
  markError: string | null;
}

/**
 * "Use this clip" (spec 10): add_drop(slug, link) files the hit's post as his drop (the link tidied as the Add clips box tidies a
 * pasted one; one the terminal cannot tidy goes as stored and the database judges it), then set_hit_status(dropped). A refused
 * add_drop throws (nothing was filed, nothing is marked). When the drop is filed but the mark is refused, that is said in the
 * result, never thrown: the clip is in Clips, and the hit must not be filed a second time by a retry.
 */
export async function fileHit(backend: Pick<Backend, 'addDrop' | 'setHitStatus'>, h: Pick<Hit, 'hit_id' | 'url'>, slug: string): Promise<FiledHit> {
  let link = h.url;
  try {
    link = canonicalVideoUrl(h.url).url;
  } catch {
    // not a link the terminal can tidy: add_drop refuses it in its own words when it is not one it takes
  }
  const { pickId, duplicate } = await backend.addDrop(slug, link);
  const status: HitStatus = 'dropped';
  try {
    await backend.setHitStatus(h.hit_id, status);
    return { pickId, duplicate, marked: true, markError: null };
  } catch (e) {
    return { pickId, duplicate, marked: false, markError: e instanceof Error ? e.message : String(e) };
  }
}

// ---- Keep (retention, spec 10) ------------------------------------------------------------------------------------------------------

/** The one line by the Keep toggle. */
export const KEEP_HINT = 'Kept clips are never deleted';

/**
 * Where the clip card shows Keep: a drop not made yet, the only clips retention deletes (studio.fetch.purge_stale: a hit's clip
 * unused for 30 days, the owner's own for 60). Not on a clip being made or made, after Make it, or on a pick queued or made: those
 * are never expired, and a Keep there would promise something it does not do.
 */
export function keepable(r: Pick<TrackerRow, 'drop_card' | 'status' | 'make_requested_at'>): boolean {
  const d = r.drop_card;
  if (!d) return false;
  if (d.state === 'making' || d.state === 'made' || r.make_requested_at) return false;
  return ['new', 'approved', 'analysed'].includes(r.status);
}
