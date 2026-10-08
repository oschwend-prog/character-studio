// Clip cards you can see and watch (terminal v3 Task 11, owner 2026-10-08: "make them larger so I can actually see them, maybe it's
// cards. Even better if I could click and watch them" and "this needs to be super user friendly and easy to produce"). What a card
// shows (the check's cover, else the middle frame of its five-frame strip, else the pick's own tile), what its play button plays
// (playableFor) and its few words. Pure functions; the components are components/ClipCard.tsx.
import { effectiveDrop } from './drop';
import type { DropCard } from './types';

/**
 * A file the owner's browser may read and the live backend signs: sources/owner/<pick id>/<file> (the storage policy of 0008).
 * The file segment starts with a letter, digit, "_" or "-" and goes on with those and "."; so never "." or "..", never a
 * percent-encoded "%2e%2e", a space or a slash (one folder level only).
 */
export const OWNER_MEDIA_PATH = /^owner\/[0-9a-f-]{36}\/[A-Za-z0-9_-][A-Za-z0-9._-]*$/i;

export function isOwnerMediaPath(path: unknown): path is string {
  return typeof path === 'string' && OWNER_MEDIA_PATH.test(path);
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
 *   `from` is `preview` (the check's watch copy: the section the check chose, played whole) or `upload` (the owner's own file,
 *   played from the start to the end of the section Make it will use). `note` is the one muted line the sheet shows when the
 *   watch copy is of another section than the one that will be made (the owner's Adjust moved it); null otherwise;
 * - `link`: the original post, opened in a new tab ("Watch on TikTok ↗");
 * - `none`: nothing to play (no play button; the card still shows).
 */
export type Playable =
  | { kind: 'file'; path: string; from: 'preview' | 'upload'; start: number; end: number | null; note: string | null }
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

interface Section {
  start: number;
  length: number;
}
const validSection = (start: unknown, length: unknown): Section | null =>
  finite(start) && finite(length) && start >= 0 && length > 0 ? { start, length } : null;

/** The section the check chose (drop_card.window), or null before the check. */
function checkedSection(d: Partial<DropCard> | null | undefined): Section | null {
  return validSection(d?.window?.start_s, d?.window?.length_s);
}

/** The section Make it will use: the owner's Adjust over the check's window (the same effectiveDrop the price uses), or null
 * before the check (unless his Adjust gave both numbers). */
function effectiveSection(d: Partial<DropCard> | null | undefined): Section | null {
  if (!d) return null;
  if (!checkedSection(d) && !(finite(d.adjust?.start_s) && finite(d.adjust?.length_s))) return null;
  const e = effectiveDrop(d as DropCard, d.adjust ?? {});
  return validSection(e.start_s, e.length_s);
}

const SAME_S = 0.05;
const differs = (a: Section, b: Section) => Math.abs(a.start - b.start) > SAME_S || Math.abs(a.length - b.length) > SAME_S;
const n1 = (x: number) => String(Number(x.toFixed(1)));
const span = (s: Section) => `${n1(s.start)}–${n1(s.start + s.length)} s`;

/** The muted line under the video when the watch copy is of another section than the one that will be made. */
export function sectionNote(checked: Section, yours: Section): string {
  return `This shows the section the check chose (${span(checked)}); yours is ${span(yours)}.`;
}

/**
 * What plays, in this order:
 * 1. when the owner's Adjust moved the section (the effective section differs from the checked window) AND his own file
 *    (owner_clip_path, under owner/<pick>/) exists: that file from the start to the end of the section Make it will use;
 * 2. else the check's watch copy of the section it chose (drop_card.preview_video_path); when the Adjust moved the section
 *    the sheet says so in one muted line (`note`);
 * 3. else the owner's own upload from the start to the end of the section;
 * 4. else the original post on TikTok, Instagram or YouTube in a new tab (a hit has no file: always this);
 * 5. else nothing.
 */
export function playableFor(row: PlayableSource): Playable {
  const d = row.drop_card ?? null;
  const checked = checkedSection(d);
  const yours = effectiveSection(d);
  const moved = checked != null && yours != null && differs(checked, yours);
  const upload = isOwnerMediaPath(row.owner_clip_path) ? row.owner_clip_path : null;
  const fromUpload = (): Playable => ({
    kind: 'file', path: upload!, from: 'upload', start: yours?.start ?? 0, end: yours ? round3(yours.start + yours.length) : null, note: null,
  });
  if (moved && upload) return fromUpload();
  if (isOwnerMediaPath(d?.preview_video_path)) {
    return {
      kind: 'file', path: d!.preview_video_path!, from: 'preview', start: 0, end: null, note: moved ? sectionNote(checked!, yours!) : null,
    };
  }
  if (upload) return fromUpload();
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

/** Where a card's picture is: which of its files it shows (`step`) and whether that file's URL was signed again after a failure. */
export interface PicturePos {
  step: number;
  resigned: boolean;
}

/** A picture failed to load: a signed URL may simply have expired, so the same file is signed once more; the second failure gives
 * way to the next file (the strip, then the pick's own thumbnail). */
export function afterPictureError(pos: PicturePos): PicturePos {
  return pos.resigned ? { step: pos.step + 1, resigned: false } : { step: pos.step, resigned: true };
}

/** Remove a clip, in two steps: the first tap only asks ("Remove this clip? Yes, remove / Keep it"); only the second removes. */
export type RemoveStep = 'idle' | 'asking';
export type RemoveAction = 'ask' | 'confirm' | 'cancel';

export function removeStep(step: RemoveStep, action: RemoveAction): { step: RemoveStep; remove: boolean } {
  if (action === 'cancel') return { step: 'idle', remove: false };
  if (action === 'confirm' && step === 'asking') return { step: 'idle', remove: true };
  return { step: 'asking', remove: false }; // "ask", or a "confirm" that was never asked for
}
