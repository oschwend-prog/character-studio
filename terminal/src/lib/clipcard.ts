// Clip cards you can see and watch (terminal v3 Task 11, owner 2026-10-08: "make them larger so I can actually see them, maybe it's
// cards. Even better if I could click and watch them" and "this needs to be super user friendly and easy to produce"). What a card
// shows (the check's cover, else the middle frame of its five-frame strip, else the pick's own tile), what its play button plays
// (playableFor) and its few words. Pure functions; the components are components/ClipCard.tsx.
import type { DropAdjust, DropCard } from './types';

/** A file the owner's browser may read and the live backend signs: sources/owner/<pick id>/<file> (the storage policy of 0008). */
export const OWNER_MEDIA_PATH = /^owner\/[0-9a-f-]{36}\/[^/\s]+$/i;

export function isOwnerMediaPath(path: unknown): path is string {
  return typeof path === 'string' && OWNER_MEDIA_PATH.test(path) && !path.split('/').includes('..');
}

export type WatchPlatform = 'tiktok' | 'instagram' | 'youtube';
export const WATCH_ON: Record<WatchPlatform, string> = { tiktok: 'TikTok', instagram: 'Instagram', youtube: 'YouTube' };

const HOSTS: ReadonlyArray<[WatchPlatform, RegExp]> = [
  ['tiktok', /(^|\.)tiktok\.com$/],
  ['instagram', /(^|\.)instagram\.com$/],
  ['youtube', /(^|\.)youtube\.com$|^youtu\.be$/],
];

/** The original post as an https link on TikTok, Instagram or YouTube (what "Watch on …" and "Open the original" open), or null. */
export function originalLink(url: string | null | undefined): { url: string; platform: WatchPlatform } | null {
  if (typeof url !== 'string' || !url.trim() || /\s/.test(url.trim())) return null;
  let u: URL;
  try {
    u = new URL(url.trim());
  } catch {
    return null;
  }
  if (u.protocol !== 'https:') return null;
  const host = u.hostname.toLowerCase().replace(/\.$/, '');
  const hit = HOSTS.find(([, re]) => re.test(host));
  return hit ? { url: u.href, platform: hit[0] } : null;
}

/**
 * What a card's play button does:
 * - `file`: a file of ours in sources/owner/ to sign and play in the player sheet, from `start` to `end` (null: to its end);
 *   `from` is `preview` (the check's watch copy: the section itself, played whole) or `upload` (the owner's own file, played from
 *   the start to the end of the section);
 * - `link`: the original post, opened in a new tab ("Watch on TikTok ↗");
 * - `none`: nothing to play (no play button; the card still shows).
 */
export type Playable =
  | { kind: 'file'; path: string; from: 'preview' | 'upload'; start: number; end: number | null }
  | { kind: 'link'; url: string; platform: WatchPlatform; label: string }
  | { kind: 'none' };

/** What playableFor reads: a v_tracker row (a drop), or a hit (its post link only). */
export interface PlayableSource {
  url?: string | null;
  platform?: string | null;
  owner_clip_path?: string | null;
  drop_card?: Partial<DropCard> | null;
}

const finite = (x: unknown): x is number => typeof x === 'number' && Number.isFinite(x);

/** The section Make it would use (the owner's Adjust over the check's window), or null before the check. */
function sectionOf(d: { window?: DropCard['window']; adjust?: DropAdjust } | null | undefined): { start: number; length: number } | null {
  const start = d?.adjust?.start_s ?? d?.window?.start_s;
  const length = d?.adjust?.length_s ?? d?.window?.length_s;
  return finite(start) && finite(length) && start >= 0 && length > 0 ? { start, length } : null;
}

/**
 * What plays, in this order: 1. the check's watch copy of the section (drop_card.preview_video_path); 2. else the owner's own
 * upload (owner_clip_path, under owner/<pick>/) from the start to the end of the section; 3. else the original post on TikTok,
 * Instagram or YouTube in a new tab (a hit has no file: always this); 4. else nothing.
 */
export function playableFor(row: PlayableSource): Playable {
  const d = row.drop_card ?? null;
  if (isOwnerMediaPath(d?.preview_video_path)) {
    return { kind: 'file', path: d!.preview_video_path!, from: 'preview', start: 0, end: null };
  }
  if (isOwnerMediaPath(row.owner_clip_path)) {
    const s = sectionOf(d);
    return { kind: 'file', path: row.owner_clip_path, from: 'upload', start: s?.start ?? 0, end: s ? round3(s.start + s.length) : null };
  }
  const link = originalLink(row.url);
  if (link) return { kind: 'link', url: link.url, platform: link.platform, label: `Watch on ${WATCH_ON[link.platform]} ↗` };
  return { kind: 'none' };
}

const round3 = (x: number) => Math.round(x * 1000) / 1000;
const secs = (x: number) => String(round3(x));

/** The W3C media fragment of a section: "#t=1.5,10.5"; "" for the whole file. */
export function mediaFragment(start: number, end: number | null): string {
  if (end == null) return start > 0 ? `#t=${secs(start)}` : '';
  return `#t=${secs(start)},${secs(end)}`;
}

/** A signed URL with the section's fragment (any fragment it had is replaced). */
export function withFragment(url: string, start: number, end: number | null): string {
  return url.replace(/#.*$/, '') + mediaFragment(start, end);
}

/** The player is at the end of the section: back to its start (a browser stops at a fragment's end and does not loop it). */
export function shouldLoopBack(currentTime: number, start: number, end: number | null): boolean {
  return end != null && currentTime >= start && currentTime >= end - 0.05;
}

/** The card's picture, best first: the check's cover, then its five-frame strip (the card shows its middle frame); none of them
 * readable by the owner's browser: [] (the card shows the pick's own thumbnail or tile). */
export function pictureSources(d: Partial<DropCard> | null | undefined): { kind: 'cover' | 'strip'; path: string }[] {
  const out: { kind: 'cover' | 'strip'; path: string }[] = [];
  if (isOwnerMediaPath(d?.cover_path)) out.push({ kind: 'cover', path: d!.cover_path! });
  if (isOwnerMediaPath(d?.preview_path)) out.push({ kind: 'strip', path: d!.preview_path! });
  return out;
}

/** "about 102 credits · 9 s": the price of Make it and the length of the section; "priced by the check" before it. */
export function cardPrice(credits: number | null | undefined, seconds: number | null | undefined): string {
  if (!finite(credits)) return 'priced by the check';
  return finite(seconds) ? `about ${credits} credits · ${Number(seconds.toFixed(1))} s` : `about ${credits} credits`;
}

/** The ready card's one action: a toggle of the same tick the Make bar adds up (nothing is spent before its confirm). */
export const MAKE_TOGGLE = {
  off: { mark: '＋', text: 'Make this' },
  on: { mark: '✓', text: 'In your list' },
} as const;
