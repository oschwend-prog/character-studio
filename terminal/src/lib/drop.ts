// "Drop a video" (plan 2026-10-06): the owner drops videos on "In the works", each becomes a row of the drops table that moves
// by itself (Uploading → Checking → Ready: about N credits) until the owner taps Make it; then it follows the 8 tracker steps.
// Owner 2026-10-06: any of his characters can go into any drop (the row's menu, set_drop_character of migration 0013), the
// studio recommends one (★, drop_card.recommended), and only the section we use is judged for text and watermarks
// (drop_card.avoid). Pure functions over v_tracker rows (drop_card, migration 0012) and the owner's Adjust; no browser. The
// rules mirror studio.drop (validate_adjust, estimate) and request_job in migration 0012: the database and the CLI check them.
import { nameOf, type RosterEntry } from './roster';
import { CLIP_MAX_SECONDS, canonicalVideoUrl, estimateCredits } from './rules';
import type { DropAdjust, DropAvoid, DropCard, DropState, OwnerPresence, TrackerRow } from './types';

export const DROP_MIN_SECONDS = 6; // a master is 6-16 s
export const DROP_MAX_SECONDS = 16;
export const ADJUST_KEYS = ['star', 'part', 'gadgets', 'hook', 'start_s', 'length_s', 'crop_x'] as const;
const SLACK_S = 0.15;
/** An upload that has not reached Checking after this long did not finish (the phone slept, the tab closed). */
export const STALE_UPLOAD_MINUTES = 30;
const MINUTE = 60_000;

export const DROP_STATE_LABEL: Record<DropState, string> = {
  uploading: 'Uploading',
  checking: 'Checking',
  waiting: 'Waiting for the Mac',
  ready: 'Ready',
  blocked: 'Can’t use this one',
  making: 'Making',
  made: 'Made',
  failed: 'Failed',
};

export const PART_LABEL: Record<OwnerPresence, string> = { cameo: 'Cameo', featured: 'Featured', star: 'Star' };

/** Is this row a dropped video still on its own card (before Make it, or blocked / failed), rather than on the 8-step stepper? */
export function isDropCard(r: Pick<TrackerRow, 'drop_card' | 'clip_id' | 'clip_state'>): boolean {
  const d = r.drop_card;
  if (!d) return false;
  if (d.state === 'ready' || d.state === 'blocked' || d.state === 'failed') return true;
  if (d.state === 'making' || d.state === 'made') return false; // the stepper takes over at Make it
  return r.clip_state == null;
}

/** The card's title: what happens in the clip (the check's own sentence), else "Your video" / "Your link". */
export function dropTitle(r: Pick<TrackerRow, 'concept' | 'drop_card'>): string {
  const line = (r.concept ?? '').split(/\r?\n/).map((l) => l.trim()).find(Boolean);
  if (line) return line;
  return r.drop_card?.kind === 'link' ? 'Your link' : 'Your video';
}

const n = (x: number) => String(Number(x.toFixed(1)));

/** "1.5–9.5 s (8 s)": a section of the clip. */
export function sectionLabel(start: number, length: number): string {
  return `${n(start)}–${n(start + length)} s (${n(length)} s)`;
}

/** The first moment with text or a watermark on screen that the section `start`..`start + length` shows, or null. */
export function avoidHit(start: number, length: number, avoid: ReadonlyArray<DropAvoid> | undefined): DropAvoid | null {
  return (avoid ?? []).find((x) => start < x.end_s - 1e-9 && start + length > x.start_s + 1e-9) ?? null;
}

/** "text on screen 0–5.5 s": when the check saw text or a watermark (the section keeps clear of it); null when it saw none. */
export function avoidLabel(d: Pick<DropCard, 'avoid'>): string | null {
  const spans = d.avoid ?? [];
  if (!spans.length) return null;
  return spans.map((x) => `${x.what === 'watermark' ? 'a watermark' : 'text'} on screen ${n(x.start_s)}–${n(x.end_s)} s`).join(', ');
}

/** Is the dropped clip landscape (wider than 9:16), so a crop around the star applies? */
export function isLandscape(d: Pick<DropCard, 'width' | 'height'>): boolean {
  return Boolean(d.width && d.height && d.width > (d.height * 9) / 16 + 1);
}

/**
 * The longest section Make it can take for this drop: 16 s, less what the character's kit adds before the dance. The check
 * writes it (`drop.max_length_s`: Reginald's pause leaves 15.6 s) and the CLI refuses a longer one at Make it, after the owner
 * tapped it, so the Adjust checks it first. 16 s when the card has none (a drop checked before it was written).
 */
export function maxSectionSeconds(d: Pick<DropCard, 'max_length_s'>): number {
  const m = d.max_length_s;
  return typeof m === 'number' && Number.isFinite(m) && m >= DROP_MIN_SECONDS && m <= DROP_MAX_SECONDS ? m : DROP_MAX_SECONDS;
}

/** What Make it will use: the check's choices with the owner's Adjust on top (like studio.drop.effective). */
export function effectiveDrop(d: DropCard, adjust: DropAdjust = {}) {
  return {
    star: adjust.star ?? d.star?.description ?? 'the main performer',
    part: adjust.part ?? d.part ?? 'featured',
    gadgets: adjust.gadgets ?? d.gadgets ?? [],
    hook: adjust.hook ?? d.hook ?? d.hooks?.[0] ?? '',
    start_s: adjust.start_s ?? d.window?.start_s ?? 0,
    length_s: adjust.length_s ?? d.window?.length_s ?? 8,
    crop_x: adjust.crop_x !== undefined ? adjust.crop_x : d.crop_x ?? null,
  };
}

/** The credits of Make it for this section: a Drop-in of that many seconds keeping the clip's own sound (estimate_credits). */
export function dropCredits(d: DropCard, adjust: DropAdjust = {}): number {
  return estimateCredits('dropin', effectiveDrop(d, adjust).length_s, 'original');
}

/**
 * The owner's Adjust, checked like studio.drop.validate_adjust and request_job (migration 0012): who is replaced and the hook
 * 1-80 characters on one line, his part, at most 3 gadgets of 1-40 characters, a section of 6-16 s (less his kit's pause:
 * drop_card.max_length_s) inside the clip and clear of
 * the text and watermark moments (drop_card.avoid: refused here and by the CLI before anything is spent), a crop from 0 to 1
 * only for a landscape clip.
 */
export function validateAdjust(adjust: DropAdjust, d: DropCard): { ok: true } | { ok: false; reason: string } {
  const bad = (reason: string) => ({ ok: false as const, reason });
  const unknown = Object.keys(adjust).filter((k) => !(ADJUST_KEYS as ReadonlyArray<string>).includes(k));
  if (unknown.length) return bad(`unknown setting ${unknown.join(', ')}`);
  for (const key of ['star', 'hook'] as const) {
    const v = adjust[key];
    if (v !== undefined && (typeof v !== 'string' || !v.trim() || v.trim().length > 80 || /\n/.test(v))) {
      return bad(`${key === 'star' ? 'Who is replaced' : 'The hook'}: one line of 1-80 characters`);
    }
  }
  if (adjust.part !== undefined && !(adjust.part in PART_LABEL)) return bad('His part: cameo, featured or star');
  if (adjust.gadgets !== undefined) {
    const g = adjust.gadgets;
    if (!Array.isArray(g) || g.length > 3 || g.some((x) => typeof x !== 'string' || !x.trim() || x.trim().length > 40)) {
      return bad('Gadgets: at most 3, 40 characters each');
    }
  }
  if (adjust.start_s !== undefined || adjust.length_s !== undefined) {
    const e = effectiveDrop(d, adjust);
    if (!Number.isFinite(e.start_s) || !Number.isFinite(e.length_s)) return bad('The section needs numbers');
    if (e.start_s < 0) return bad('The section starts at 0 s or later');
    const longest = maxSectionSeconds(d);
    if (e.length_s < DROP_MIN_SECONDS || e.length_s > longest + 1e-9) {
      const pause = longest < DROP_MAX_SECONDS ? ` (his opening pause adds ${n(DROP_MAX_SECONDS - longest)} s: the master stays within ${DROP_MAX_SECONDS} s)` : '';
      return bad(`The section lasts ${DROP_MIN_SECONDS}-${n(longest)} s${pause}`);
    }
    if (d.duration_s && e.start_s + e.length_s > d.duration_s + SLACK_S) {
      return bad(`The section runs past the end of the ${Number(d.duration_s.toFixed(1))} s video`);
    }
    const hit = avoidHit(e.start_s, e.length_s, d.avoid); // only the section is judged: it may not show text or a watermark
    if (hit) {
      return bad(`The section shows ${hit.what === 'watermark' ? 'a watermark' : 'text'} on screen (${n(hit.start_s)}–${n(hit.end_s)} s): Genjutsu would keep it`);
    }
  }
  if (adjust.crop_x != null) {
    if (!Number.isFinite(adjust.crop_x) || adjust.crop_x < 0 || adjust.crop_x > 1) return bad('The crop is from 0 to 1');
    if (d.width && d.height && !isLandscape(d)) return bad('The video is already vertical: nothing to crop');
  }
  return { ok: true };
}

/** Only what the owner changed (an unchanged value is not sent, so the check's own choice stays the default). */
export function adjustChanges(d: DropCard, wanted: Required<Omit<DropAdjust, 'crop_x'>> & { crop_x: number | null }): DropAdjust {
  const base = effectiveDrop(d);
  const out: DropAdjust = {};
  if (wanted.star.trim() && wanted.star.trim() !== base.star) out.star = wanted.star.trim();
  if (wanted.part !== base.part) out.part = wanted.part;
  const g = wanted.gadgets.map((x) => x.trim()).filter(Boolean);
  if (g.join('\u0000') !== base.gadgets.join('\u0000')) out.gadgets = g;
  if (wanted.hook.trim() && wanted.hook.trim() !== base.hook) out.hook = wanted.hook.trim();
  if (wanted.start_s !== base.start_s || wanted.length_s !== base.length_s) {
    out.start_s = wanted.start_s;
    out.length_s = wanted.length_s;
  }
  if (isLandscape(d) && wanted.crop_x !== base.crop_x) out.crop_x = wanted.crop_x;
  return out;
}

/** "Replaces the man in the grey suit · Featured · 1–9 s (8 s)": the card's one line about what Make it will do. */
export function dropSummary(d: DropCard): string {
  const e = effectiveDrop(d, d.adjust ?? {});
  return [`Replaces ${e.star}`, PART_LABEL[e.part], sectionLabel(e.start_s, e.length_s)].join(' · ');
}

export type DropAction = 'make' | 'adjust' | 'retry-check' | 'retry-make' | 'remove';

/** The buttons a drop card offers: Make it and Adjust when ready; Try again after a failure; Remove when it cannot go on. */
export function dropActions(d: DropCard, now: number): DropAction[] {
  switch (d.state) {
    case 'ready':
      return ['make', 'adjust'];
    case 'blocked':
      return ['remove'];
    case 'failed':
      if (d.credits == null) return ['retry-check', 'remove'];
      // priced: Make it again with the stored Adjust, or Adjust it; an Adjust that no longer fits (the reason of the failure) has no retry
      return validateAdjust(d.adjust ?? {}, d).ok ? ['retry-make', 'adjust', 'remove'] : ['adjust', 'remove'];
    case 'waiting':
      return ['retry-check', 'remove'];
    case 'uploading':
      return isStaleUpload(d, now) ? ['remove'] : [];
    default:
      return [];
  }
}

/**
 * What Try again sends after a failed Make it: the Adjust the owner stored (request_job replaces it with what it is given, so
 * sending nothing would discard it and make something other than the price on the button), null when there is none.
 */
export function retryAdjust(d: DropCard): DropAdjust | null {
  return d.adjust && Object.keys(d.adjust).length ? d.adjust : null;
}

/** An upload still at Uploading after 30 minutes did not finish: the card says so and offers Remove. */
export function isStaleUpload(d: Pick<DropCard, 'state' | 'at'>, now: number): boolean {
  if (d.state !== 'uploading' || !d.at) return false;
  const at = Date.parse(d.at);
  return Number.isFinite(at) && now - at > STALE_UPLOAD_MINUTES * MINUTE;
}

/** The one line under a card's title, by state (the database's own reason wins when it gave one). */
export function dropLine(d: DropCard, now: number): string {
  if (d.reason) return d.reason;
  switch (d.state) {
    case 'uploading':
      return isStaleUpload(d, now) ? 'The upload did not finish: remove it and drop the video again' : 'Uploading to your storage';
    case 'checking':
      return 'Looking at the clip: who is in it, the best section, the price';
    case 'waiting':
      return 'The cloud could not fetch the link: the Mac’s daily run tries again';
    case 'ready':
      return dropSummary(d);
    case 'blocked':
      return 'This clip cannot be used';
    case 'making':
      return 'Make it sent: generating starts';
    case 'made':
      return 'Made: waiting for your OK';
    case 'failed':
      return 'Something failed: try again';
  }
}

// ---- the drop box -------------------------------------------------------------------------------------------------------

/** A pasted link as the canonical URL add_drop accepts, or the reason it is refused. */
export function dropLink(input: string): { ok: true; url: string } | { ok: false; reason: string } {
  try {
    return { ok: true, url: canonicalVideoUrl(input).url };
  } catch (e) {
    return { ok: false, reason: e instanceof Error ? e.message : String(e) };
  }
}

export const DROP_HELP = `Videos from your phone (up to ${CLIP_MAX_SECONDS} s and 200 MB each) or a TikTok, Instagram or YouTube link. Each one is checked for free; nothing is generated until you tap Make it.`;

/** The local progress of one dropped file in the box (before its card exists in the database). */
export type UploadPhase =
  | { phase: 'reading' }
  | { phase: 'uploading'; pct: number }
  | { phase: 'done' }
  | { phase: 'error'; message: string };

// ---- the drops table (owner 2026-10-06: one table of every dropped clip, a character menu per row) -----------------------------

/** The Drop box's default: no character, the studio recommends one after the check (add_drop with no character, migration 0013). */
export const RECOMMEND = 'recommend';

const TABLE_ORDER: Record<DropState, number> = { ready: 0, failed: 1, blocked: 2, waiting: 3, uploading: 4, checking: 4, making: 5, made: 6 };

/**
 * The drops table: every dropped video in one list, whatever its character. Ready first (the owner's Make it), then what needs
 * him (failed, blocked, waiting), then what moves by itself (uploading, checking), then what is being made or made; the newest
 * drop first within each.
 */
export function dropRows<R extends Pick<TrackerRow, 'pick_id' | 'drop_card' | 'approved_at'>>(rows: ReadonlyArray<R>): R[] {
  const at = (r: R) => Date.parse(r.drop_card?.at ?? r.approved_at) || 0;
  return rows
    .filter((r) => r.drop_card)
    .sort((a, b) => TABLE_ORDER[a.drop_card!.state] - TABLE_ORDER[b.drop_card!.state] || at(b) - at(a) || a.pick_id.localeCompare(b.pick_id));
}

/** The header line: how many drops are Ready and what making every one of them would cost (each with its own Adjust). */
export function readyTotal(rows: ReadonlyArray<Pick<TrackerRow, 'drop_card'>>): { count: number; credits: number } {
  const ready = rows.filter((r) => r.drop_card?.state === 'ready');
  return { count: ready.length, credits: ready.reduce((sum, r) => sum + dropCredits(r.drop_card!, r.drop_card!.adjust ?? {}), 0) };
}

const CHOOSABLE: ReadonlyArray<DropState> = ['uploading', 'checking', 'waiting', 'ready', 'blocked', 'failed'];

/** May the owner still choose the character (set_drop_character's own rule): before Make it, the pick neither queued nor made. */
export function canChooseCharacter(r: Pick<TrackerRow, 'drop_card' | 'status'>): boolean {
  const s = r.drop_card?.state;
  return Boolean(s && CHOOSABLE.includes(s) && r.status !== 'queued' && r.status !== 'made');
}

export interface CharacterOption {
  slug: string;
  /** "Franz ★" for the recommended one. */
  label: string;
  recommended: boolean;
  /** The row's own character when he is no longer offered (paused): shown, never chosen. */
  disabled: boolean;
}

export interface CharacterMenu {
  /** The menu's value: the row's character, or RECOMMEND while the studio has not chosen yet. */
  value: string;
  options: CharacterOption[];
  /** A Recommend drop before its check: the studio's choice is still to come (a first "Recommend" option shows it). */
  pending: boolean;
  /** The character is settled (Make it was tapped): the menu is read-only. */
  locked: boolean;
  /** The check's recommendation, named; null before the check (or from a check before 0013). */
  recommendation: { slug: string; name: string; reason: string } | null;
  /** Who chose the character shown: the owner (never overridden) or the studio (Recommend). */
  by: 'owner' | 'studio';
}

/** The row's character menu: the live roster (★ on the recommended one), the row's character, who chose it. */
export function characterMenu(
  r: Pick<TrackerRow, 'character_slug' | 'drop_card' | 'status'>,
  roster: ReadonlyArray<RosterEntry>,
): CharacterMenu {
  const d = r.drop_card;
  const by = d?.character_by === 'studio' ? 'studio' : 'owner';
  const rec = d?.recommended && d.recommended.slug ? d.recommended : null;
  const named = (slug: string) => roster.find((c) => c.slug === slug)?.name ?? nameOf(slug);
  const locked = !canChooseCharacter(r);
  const pending = by === 'studio' && !rec && !locked;
  const options: CharacterOption[] = roster.map((c) => ({
    slug: c.slug, label: rec?.slug === c.slug ? `${c.name} ★` : c.name, recommended: rec?.slug === c.slug, disabled: false,
  }));
  if (r.character_slug && !roster.some((c) => c.slug === r.character_slug)) {
    options.push({ slug: r.character_slug, label: `${named(r.character_slug)} (paused)`, recommended: false, disabled: true });
  }
  return {
    value: pending ? RECOMMEND : r.character_slug ?? RECOMMEND,
    options,
    pending,
    locked,
    recommendation: rec ? { slug: rec.slug, name: named(rec.slug), reason: rec.reason } : null,
    by,
  };
}

/**
 * The line under the menu: "★ The studio picks after the check" before a Recommend drop's check; "★ Studio's pick: <why>" when
 * the studio chose; "★ <why>" when the owner's choice is the recommended one; "★ Franz: <why>" when the star points elsewhere
 * (he may ignore it); null when there is no recommendation.
 */
export function recommendationLine(menu: CharacterMenu, current: string | null): string | null {
  if (menu.pending) return '★ The studio picks after the check';
  const rec = menu.recommendation;
  if (!rec) return null;
  if (rec.slug !== current) return `★ ${rec.name}: ${rec.reason}`;
  return menu.by === 'studio' ? `★ Studio’s pick: ${rec.reason}` : `★ ${rec.reason}`;
}
