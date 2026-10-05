import { londonDayKey, londonTime, londonWeekday } from './format';

// The owner-facing rules the terminal applies on its own side. Each one mirrors a rule the database
// (migration 0004) or the Python studio enforces; the server stays the authority, these only decide
// what the screen offers.

/** Posting autopilot unlocks per account after this many approved posts (owner directive 2026-10-04). */
export const AUTOPILOT_MIN_APPROVED = 6;

export interface AutopilotState {
  on: boolean;
  locked: boolean;
  remaining: number;
  canToggle: boolean;
  reason: string;
}

/** Whether an account's autopilot is on, locked, and what the switch may do. Switching OFF is always allowed. */
export function autopilotState(a: { mode: string; approved_posts: number | null | undefined }): AutopilotState {
  const approved = Math.max(0, a.approved_posts ?? 0);
  const remaining = Math.max(0, AUTOPILOT_MIN_APPROVED - approved);
  const locked = remaining > 0;
  const on = a.mode === 'auto';
  const reason = locked
    ? `Unlocks after ${AUTOPILOT_MIN_APPROVED} approved posts · ${approved} of ${AUTOPILOT_MIN_APPROVED} so far`
    : on
      ? 'Clips that pass QA post at the next slot without asking'
      : 'Unlocked: clips that pass QA can post without asking';
  return { on, locked, remaining, canToggle: on || !locked, reason };
}

export interface Approvable {
  id: string;
  state: string;
  master_path: string | null;
  targets: ReadonlyArray<unknown> | null;
}

/**
 * "Approve all": the clips one tap approves, and the ones it leaves (with the reason shown to the owner).
 * A clip qualifies when it is awaiting approval, has its master, at least one account can take it
 * (approve_clip refuses otherwise) and it is not already being approved. Clips in any other state are
 * not part of the queue and are ignored silently.
 */
export function selectApprovable(
  queue: ReadonlyArray<Approvable>,
  inFlight: ReadonlySet<string> = new Set(),
): { ids: string[]; skipped: { id: string; reason: string }[] } {
  const ids: string[] = [];
  const skipped: { id: string; reason: string }[] = [];
  for (const c of queue) {
    if (c.state !== 'awaiting_approval' || inFlight.has(c.id)) continue;
    if (!c.master_path) skipped.push({ id: c.id, reason: 'no master file yet' });
    else if (!c.targets || c.targets.length === 0) skipped.push({ id: c.id, reason: 'no connected account can take it' });
    else ids.push(c.id);
  }
  return { ids, skipped };
}

/** Viral Picks order (studio fav list): total score high to low, unscored last, older first on ties. */
export function sortPicks<T extends { total_score: number | null; created_at: string }>(picks: ReadonlyArray<T>): T[] {
  return [...picks].sort((a, b) => {
    const an = a.total_score == null;
    const bn = b.total_score == null;
    if (an !== bn) return an ? 1 : -1;
    const diff = (b.total_score ?? 0) - (a.total_score ?? 0);
    if (diff !== 0) return diff;
    return Date.parse(a.created_at) - Date.parse(b.created_at);
  });
}

export type SpendTone = 'ok' | 'warn' | 'over';

export const CAP_WARN_PCT = 80;

/**
 * Spend against the monthly cap. Warn at 80 % with exact integer arithmetic (studio health: 4,800 of
 * 6,000 warns, 4,799 does not); over at the cap. Projection = committed / day x days in the month.
 */
export function spendState(b: { committed: number; cap: number; day_of_month: number; days_in_month: number }) {
  const tone = (value: number): SpendTone =>
    b.cap <= 0 ? 'ok' : value >= b.cap ? 'over' : value * 100 >= b.cap * CAP_WARN_PCT ? 'warn' : 'ok';
  const projected = b.day_of_month > 0 ? Math.round((b.committed / b.day_of_month) * b.days_in_month) : b.committed;
  return {
    pct: b.cap > 0 ? (b.committed * 100) / b.cap : null,
    tone: tone(b.committed),
    projected,
    projectedPct: b.cap > 0 ? (projected * 100) / b.cap : null,
    projectedTone: tone(projected),
    remaining: Math.max(b.cap - b.committed, 0),
  };
}

// ---- owner links: the same canonical form as studio.favorites.parse_video_url ---------------------

const HOSTS: Record<string, ReadonlySet<string>> = {
  tiktok: new Set(['tiktok.com', 'www.tiktok.com', 'm.tiktok.com']),
  instagram: new Set(['instagram.com', 'www.instagram.com']),
  youtube: new Set(['youtube.com', 'www.youtube.com', 'm.youtube.com']),
};
const SHORT_HOSTS = new Set(['vm.tiktok.com', 'vt.tiktok.com', 'instagr.am', 'youtu.be']);
const W = String.raw`[\p{L}\p{N}_]`;
const TIKTOK_VIDEO = new RegExp(String.raw`^/@((?:${W}|[.\-])+)/video/(\d+)$`, 'u');
const INSTAGRAM_REEL = new RegExp(String.raw`^(?:/(?:${W}|\.)+)?/reel/((?:${W}|-)+)$`, 'u');
const YOUTUBE_SHORT = new RegExp(String.raw`^/shorts/((?:${W}|-)+)$`, 'u');
const FULL_URL_HELP =
  'https://www.tiktok.com/@user/video/<id>, https://www.instagram.com/reel/<code>/ or https://www.youtube.com/shorts/<id>';

/** `{platform, url}` for a full TikTok / Instagram Reel / YouTube Shorts link; throws with the owner-facing reason. */
export function canonicalVideoUrl(input: string): { platform: 'tiktok' | 'instagram' | 'youtube'; url: string } {
  const raw = (input ?? '').trim();
  if (!raw) throw new Error('url is required');
  let parsed: URL;
  try {
    parsed = new URL(raw.includes('://') ? raw : `https://${raw}`);
  } catch {
    throw new Error(`not a supported video URL: expected ${FULL_URL_HELP}`);
  }
  const scheme = parsed.protocol.replace(/:$/, '');
  const host = parsed.hostname.toLowerCase().replace(/\.$/, '');
  const path = decodeURIComponent(parsed.pathname).replace(/\/+$/, '');
  if (scheme === 'http' || scheme === 'https') {
    if (SHORT_HOSTS.has(host) || (HOSTS.tiktok.has(host) && path.startsWith('/t/'))) {
      throw new Error(`short links are not accepted: paste the full URL (${FULL_URL_HELP})`);
    }
    let m: RegExpMatchArray | null;
    if (HOSTS.tiktok.has(host) && (m = path.match(TIKTOK_VIDEO))) {
      return { platform: 'tiktok', url: `https://www.tiktok.com/@${m[1].toLowerCase()}/video/${m[2]}` };
    }
    if (HOSTS.instagram.has(host) && (m = path.match(INSTAGRAM_REEL))) {
      return { platform: 'instagram', url: `https://www.instagram.com/reel/${m[1]}/` };
    }
    if (HOSTS.youtube.has(host) && (m = path.match(YOUTUBE_SHORT))) {
      return { platform: 'youtube', url: `https://www.youtube.com/shorts/${m[1]}` };
    }
  }
  throw new Error(`not a supported video URL: expected ${FULL_URL_HELP}`);
}

// ---- the Today board ------------------------------------------------------------------------------


export type BoardTone = 'neutral' | 'live' | 'action' | 'warn' | 'alert' | 'muted';

export interface BoardRow {
  accountId: string;
  characterSlug: string;
  platform: string;
  handle: string | null;
  time: string; // London "19:00", or "--:--" without a slot
  day: string; // London weekday of the row's moment
  today: boolean;
  at: string | null; // ISO moment of the row
  status: 'SCHEDULED' | 'POSTING' | 'POSTED' | 'CHECK' | 'FAILED' | 'NEEDS YOU' | 'NO CLIP' | 'NEXT' | 'NOT LINKED';
  tone: BoardTone;
  clipId: string | null;
  hook: string | null;
}

const POST_STATUS: Record<string, [BoardRow['status'], BoardTone]> = {
  scheduled: ['SCHEDULED', 'neutral'],
  posting: ['POSTING', 'live'],
  posted: ['POSTED', 'live'],
  needs_check: ['CHECK', 'alert'],
  failed: ['FAILED', 'alert'],
};

interface BoardChannel {
  account_id: string;
  character_slug: string;
  platform: string;
  handle: string | null;
  connected: boolean;
  next_slot: string | null;
  today_posts: ReadonlyArray<{ clip_id: string; scheduled_for: string; status: string; hook: string | null }>;
}

/**
 * One departure-board row per channel: today's post if there is one (the latest still to go, else
 * the last one), otherwise what today's slot is waiting for, otherwise the next cadence day.
 */
export function boardRows(
  channels: ReadonlyArray<BoardChannel>,
  queue: ReadonlyArray<{ id: string; character_slug: string; hook: string | null }>,
  now: number = Date.now(),
): BoardRow[] {
  const today = londonDayKey(now);
  const rows = channels.map((c): BoardRow => {
    const base = {
      accountId: c.account_id, characterSlug: c.character_slug, platform: c.platform, handle: c.handle,
    };
    const posts = [...c.today_posts].sort((a, b) => Date.parse(a.scheduled_for) - Date.parse(b.scheduled_for));
    const post = posts.find((p) => p.status === 'scheduled' || p.status === 'posting') ?? posts[posts.length - 1];
    if (post) {
      const [status, tone] = POST_STATUS[post.status] ?? ['SCHEDULED', 'neutral'];
      return {
        ...base, time: londonTime(post.scheduled_for), day: londonWeekday(post.scheduled_for), today: true,
        at: post.scheduled_for, status, tone, clipId: post.clip_id, hook: post.hook,
      };
    }
    const at = c.next_slot;
    const slotToday = at != null && londonDayKey(at) === today;
    const timing = {
      time: at ? londonTime(at) : '--:--', day: at ? londonWeekday(at) : '', today: slotToday, at,
    };
    if (!c.connected) return { ...base, ...timing, status: 'NOT LINKED', tone: 'muted', clipId: null, hook: null };
    if (!slotToday) return { ...base, ...timing, status: 'NEXT', tone: 'neutral', clipId: null, hook: null };
    const waiting = queue.find((q) => q.character_slug === c.character_slug);
    if (waiting) return { ...base, ...timing, status: 'NEEDS YOU', tone: 'action', clipId: waiting.id, hook: waiting.hook };
    return { ...base, ...timing, status: 'NO CLIP', tone: 'warn', clipId: null, hook: null };
  });
  return rows.sort(
    (a, b) =>
      (a.at ? Date.parse(a.at) : Infinity) - (b.at ? Date.parse(b.at) : Infinity) ||
      a.characterSlug.localeCompare(b.characterSlug) ||
      a.platform.localeCompare(b.platform),
  );
}
