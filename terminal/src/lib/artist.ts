// The artist page (`#/artist/<slug>`, owner 2026-10-06): one page per character with who he is (from his bible, through
// src/generated/artists.json, which scripts/build-artists.mjs writes at build time) and how he is doing (from the data the terminal
// already loads: the seeded character, his accounts, "In the works", the Queue and the Library). Pure functions, no browser.
import { DROP_STATE_LABEL, dropTitle, isDropCard } from './drop';
import { TRACKER_STEPS, trackerStep, trackerTitle } from './tracker';
import type { Character, Snapshot } from './types';

/** One line of a bible list, with its nested lines. */
export interface ArtistItem {
  text: string;
  children?: ArtistItem[];
}

export interface ArtistGadget {
  name: string;
  /** "ready", "idea", ... as the bible's table says (null when it came from the traits card). */
  status: string | null;
  /** The viral job it does. */
  job: string | null;
}

export interface ArtistAccount {
  platform: string;
  handle: string | null;
  planned: string | null;
  connected: boolean;
}

/** One character's card as build-artists.mjs writes it (refs.json + bible.md + social.md). */
export interface Artist {
  slug: string;
  name: string;
  status: string;
  concept: string | null;
  /** The caption title's "· <edition> edition". */
  edition: string | null;
  images: {
    /** Public paths of the build's copies of assets/characters/<slug>/ (null when there was none). */
    spec: string | null;
    turnaround: string | null;
    avatar: string | null;
    /** The Higgsfield CDN URLs of refs.json reference_urls (the turnaround sheet and the master). */
    turnaround_url: string | null;
    master_url: string | null;
  };
  look: ArtistItem[];
  wardrobe: { signature: ArtistItem[]; capsule: ArtistItem[] };
  motion: ArtistItem[];
  signature_move: { text: string | null; notes: ArtistItem[] };
  catchphrase: { line: string | null; text: string | null; notes: ArtistItem[] };
  voice: { preset: string | null; voice_id: string | null; sample_url: string | null; items: ArtistItem[] };
  gadgets: ArtistGadget[];
  swap: { text: string | null; noun: string | null; stars: string[] };
  accounts: ArtistAccount[];
}

export type InlinePart = { kind: 'text' | 'strong' | 'code'; text: string };

/** A bible line as plain parts: `**bold**`, `` `code` `` and the rest; a markdown link keeps its words only. */
export function inlineParts(text: string): InlinePart[] {
  const plain = text.replace(/\[([^\]]+)\]\([^)]*\)/g, '$1');
  const out: InlinePart[] = [];
  const re = /\*\*(.+?)\*\*|`([^`]+)`/g;
  let at = 0;
  for (let m = re.exec(plain); m; m = re.exec(plain)) {
    if (m.index > at) out.push({ kind: 'text', text: plain.slice(at, m.index) });
    out.push(m[1] != null ? { kind: 'strong', text: m[1].replace(/`/g, '') } : { kind: 'code', text: m[2] });
    at = m.index + m[0].length;
  }
  if (at < plain.length) out.push({ kind: 'text', text: plain.slice(at) });
  return out;
}

/** The artist card of `slug` among the generated ones, or null. */
export function findArtist(slug: string | null | undefined, artists: ReadonlyArray<Artist>): Artist | null {
  return (slug && artists.find((a) => a.slug === slug)) || null;
}

/** The like-for-like line of refs.json `swap.stars`: ["person"] -> "Replaces a person". */
export function swapLine(stars: ReadonlyArray<string>): string | null {
  const words: Record<string, string> = { person: 'a person', dog: 'a dog', animal: 'a small animal' };
  const list = stars.map((s) => words[s] ?? s);
  return list.length ? `Replaces ${list.join(' or ')}` : null;
}

export interface ArtistAccountView {
  platform: 'instagram' | 'tiktok';
  handle: string | null;
  /** live = connected in Postiz; linked = the account exists but is not connected; planned = not created yet. */
  state: 'live' | 'linked' | 'planned';
}

/**
 * His two accounts: the seeded ones first (handle, Postiz connected or not), else what is planned (characters.setup.planned_handles,
 * else the card's refs.json / social.md handle).
 */
export function artistAccounts(artist: Artist | null, character: Pick<Character, 'accounts' | 'setup'> | null): ArtistAccountView[] {
  return (['instagram', 'tiktok'] as const).map((platform) => {
    const seeded = character?.accounts.find((a) => a.platform === platform && a.handle?.trim());
    if (seeded) return { platform, handle: seeded.handle!.trim(), state: seeded.has_postiz ? 'live' : 'linked' };
    const card = artist?.accounts.find((a) => a.platform === platform);
    if (!character && card?.handle) return { platform, handle: card.handle, state: card.connected ? 'live' : 'linked' };
    return { platform, handle: character?.setup?.planned_handles?.[platform] ?? card?.planned ?? null, state: 'planned' };
  });
}

export interface ArtistVideo {
  id: string;
  title: string;
  /** Where it is: the tracker step, "Your OK", or the post date. */
  where: string;
  /** The page to open it on. */
  route: 'works' | 'queue' | 'library';
  views?: number | null;
  outlierX?: number | null;
}

export interface ArtistVideos {
  works: ArtistVideo[];
  queue: ArtistVideo[];
  posted: ArtistVideo[];
  stats: {
    inTheWorks: number;
    waiting: number;
    posted: number;
    /** Views of his posted clips (null before any is measured). */
    views: number | null;
    /** His best outlier (null before any is measured). */
    bestX: number | null;
    /** Credits committed for him this month (the budget's row; 0 without one). */
    creditsMonth: number;
  };
}

const ts = (iso: string | null | undefined) => (iso ? Date.parse(iso) : 0);

/** His videos from what the terminal loads: In the works (the tracker), waiting for the owner (the Queue), posted (the Library). */
export function artistVideos(slug: string, data: Pick<Snapshot, 'tracker' | 'queue' | 'library' | 'budget'>, now: number): ArtistVideos {
  const works = data.tracker
    .filter((r) => r.character_slug === slug)
    .map((r) => {
      // a dropped video on its own card (Uploading, Checking, Ready, ...) is named as "In the works" names it
      if (isDropCard(r)) return { id: r.pick_id, title: dropTitle(r), where: DROP_STATE_LABEL[r.drop_card!.state], route: 'works' as const };
      const s = trackerStep(r, now);
      return { id: r.pick_id, title: trackerTitle(r), where: TRACKER_STEPS[s.step - 1], route: 'works' as const };
    });
  const queue = data.queue
    .filter((c) => c.character_slug === slug)
    .map((c) => ({ id: c.id, title: c.hook ? `“${c.hook}”` : 'untitled clip', where: 'Your OK', route: 'queue' as const }));
  const postedClips = data.library
    .filter((c) => c.character_slug === slug && c.state === 'posted')
    .sort((a, b) => ts(b.posted_at ?? b.created_at) - ts(a.posted_at ?? a.created_at));
  const posted = postedClips.map((c) => ({
    id: c.id, title: c.hook ? `“${c.hook}”` : 'untitled clip', where: c.posted_at ?? c.created_at, route: 'library' as const,
    views: c.views, outlierX: c.outlier_x,
  }));
  const measured = postedClips.filter((c) => typeof c.views === 'number');
  const xs = postedClips.map((c) => c.outlier_x).filter((x): x is number => typeof x === 'number');
  return {
    works,
    queue,
    posted,
    stats: {
      inTheWorks: works.length,
      waiting: queue.length,
      posted: posted.length,
      views: measured.length ? measured.reduce((s, c) => s + (c.views ?? 0), 0) : null,
      bestX: xs.length ? Math.max(...xs) : null,
      creditsMonth: data.budget?.by_character.find((c) => c.slug === slug)?.committed ?? 0,
    },
  };
}
