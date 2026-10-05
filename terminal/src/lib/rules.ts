import { londonDate, londonDayKey, londonTime, londonWallToIso, londonWeekday } from './format';
import type {
  Channel, Character, DecideExtras, LibraryClip, OwnerMode, OwnerPresence, Pick as ViralPick, PickHistory, QueueClip, RunRow,
  ScanDetails, Snapshot,
} from './types';

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

/**
 * Whether an account's autopilot is on, locked, and what the switch may do. Switching OFF is always
 * allowed. The daily run only skips the approval queue when EVERY connected account of the character is
 * on autopilot, so the copy says so when a sibling channel is still on approval (`ctx`).
 */
export function autopilotState(
  a: { mode: string; approved_posts: number | null | undefined },
  ctx: { characterName?: string; allConnectedAuto?: boolean } = {},
): AutopilotState {
  const approved = Math.max(0, a.approved_posts ?? 0);
  const remaining = Math.max(0, AUTOPILOT_MIN_APPROVED - approved);
  const locked = remaining > 0;
  const on = a.mode === 'auto';
  const who = ctx.characterName ?? 'this character';
  const theirs = ctx.characterName ? `${ctx.characterName} clips` : 'clips';
  let reason: string;
  if (locked) reason = `Unlocks after ${AUTOPILOT_MIN_APPROVED} approved posts · ${approved} of ${AUTOPILOT_MIN_APPROVED} so far`;
  else if (on && ctx.allConnectedAuto === false)
    reason = `On, but ${theirs} still wait for you until every connected ${who} channel is on autopilot`;
  else if (on) reason = `On: ${theirs} that pass QA post at the next slot without asking`;
  else reason = `Unlocked. Posting is automatic only when every connected ${who} channel is on autopilot`;
  return { on, locked, remaining, canToggle: on || !locked, reason };
}

export interface Approvable {
  id: string;
  state: string;
  master_path: string | null;
  targets: ReadonlyArray<unknown> | null;
  /** The database's own answer (v_queue.blocked_reason, migration 0005): NULL when it can be approved. */
  blocked_reason?: string | null;
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
    if (c.blocked_reason) skipped.push({ id: c.id, reason: c.blocked_reason });
    else if (!c.master_path) skipped.push({ id: c.id, reason: 'no master file yet' });
    else if (!c.targets || c.targets.length === 0) skipped.push({ id: c.id, reason: 'no connected account can take it' });
    else ids.push(c.id);
  }
  return { ids, skipped };
}

/**
 * Approve clips one by one (the RPC is per clip), never stopping at a refusal: one bad clip must not
 * hold back the others. Returns the count and the refusals for one toast.
 */
export async function approveAll(
  backend: { approveClip(id: string): Promise<unknown> },
  ids: ReadonlyArray<string>,
): Promise<{ approved: number; refused: string[]; summary: string }> {
  let approved = 0;
  const refused: string[] = [];
  for (const id of ids) {
    try {
      await backend.approveClip(id);
      approved += 1;
    } catch (e) {
      refused.push(e instanceof Error ? e.message : String(e));
    }
  }
  const summary = refused.length ? `${approved} approved, ${refused.length} refused: ${refused[0]}` : `${approved} approved`;
  return { approved, refused, summary };
}

/**
 * Which clip the queue pager shows: the one decision, so no two effects race.
 * 1. A deep link (#/queue/<id>) not applied yet wins once its clip is in the queue (it stays pending
 *    while the queue loads).
 * 2. Otherwise the clip being viewed stays, whatever reloads happen (Realtime, focus, the minute poll).
 * 3. Otherwise, when the clip being viewed left the queue (approved, rejected, regenerated, or gone in a
 *    Realtime reload), the clip that took its place: `ids[min(lastIndex, ids.length - 1)]`, where
 *    `lastIndex` is the position the viewed clip had. Approving clip 2 of 3 lands on the former clip 3
 *    (now 2 of 2); removing the last clip lands on the new last one.
 * 4. Nothing chosen yet: the first clip. An empty queue is null.
 * Returns the id to show and the deep link now counted as applied.
 */
export function nextCurrentId(s: {
  ids: ReadonlyArray<string>;
  currentId: string | null;
  focus: string | null;
  appliedFocus: string | null;
  lastIndex: number;
}): { id: string | null; appliedFocus: string | null } {
  if (s.focus && s.focus !== s.appliedFocus && s.ids.includes(s.focus)) return { id: s.focus, appliedFocus: s.focus };
  if (s.currentId && s.ids.includes(s.currentId)) return { id: s.currentId, appliedFocus: s.appliedFocus };
  if (s.currentId && s.ids.length) {
    const at = Math.min(Math.max(s.lastIndex, 0), s.ids.length - 1);
    return { id: s.ids[at] ?? null, appliedFocus: s.appliedFocus };
  }
  return { id: s.ids[0] ?? null, appliedFocus: s.appliedFocus };
}

/**
 * What one approval does with the slot (migration 0006 free_slot, planning.free_slot): the first cadence slot
 * on a day none of the clip's channels already has a post, so two approved clips never share a day. The
 * publisher still posts at most 2 per channel per London day.
 */
export const SLOT_RULE = 'Each posts at the first free slot: the next posting day on which the channel has no post yet';

/** Under the time picker: the daily cap, and when a time you chose yourself actually goes out. */
export const SCHEDULE_NOTE =
  'At most 2 posts per channel per day: a third waits for the next free slot. A time outside the evening posting window goes out within about 3 hours of it.';

/** The kill switch stops generation AND posting (spec): every place that names it uses this wording. */
export const KILL_SWITCH_COPY = {
  stopButton: 'Stop all new spend and posting',
  stopArming: 'Tap again to stop all spend and posting',
  resumeButton: 'Resume spending and posting',
  resumeArming: 'Tap again to resume spending and posting',
  on: 'On. Nothing is generated or posted until you switch it off: the daily run makes nothing, and approved clips wait in their slots and go out once it is off.',
  off: 'Off. The daily run may reserve credits up to the cap, and approved clips post at their slots.',
  toastOn: 'Kill switch on: nothing is generated or posted',
  toastOff: 'Kill switch off: the daily run and posting resume',
  today: 'Kill switch is on: nothing is generated or posted until you switch it off.',
} as const;

/** A caption or hook edit for approve_clip: the trimmed text when it changed, else null (keep). Never ''. */
export function captionEdit(value: string, original: string | null): string | null {
  const v = value.trim();
  if (!v || v === (original ?? '').trim()) return null;
  return v;
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


// ---- the Characters page --------------------------------------------------------------------------

export interface ChecklistItem {
  id: 'tiktok' | 'instagram' | 'postiz' | 'closeup' | 'live';
  label: string;
  done: boolean;
  /** One short line under the label: the handle, what is planned, how many are connected. */
  detail: string;
}

const hasHandle = (a: { handle: string | null }) => Boolean(a.handle?.trim());

/**
 * The go-live checklist of one character (the order of docs/launch/go-live.md): a TikTok account, an Instagram
 * account, every account connected in Postiz, the eye close-up shot ready, and the character live. `ready` is
 * everything before "Live" done: the owner may flip the status.
 */
export function goLiveChecklist(c: Pick<Character, 'status' | 'setup' | 'accounts'>): {
  items: ChecklistItem[];
  done: number;
  total: number;
  ready: boolean;
} {
  const accounts = c.accounts.filter(hasHandle);
  const account = (platform: 'tiktok' | 'instagram', label: string): ChecklistItem => {
    const found = accounts.find((a) => a.platform === platform);
    const planned = c.setup?.planned_handles?.[platform];
    return {
      id: platform,
      label,
      done: Boolean(found),
      detail: found ? found.handle!.trim() : planned ? `planned ${planned}` : 'not created yet',
    };
  };
  const connected = accounts.filter((a) => a.has_postiz).length;
  const items: ChecklistItem[] = [
    account('tiktok', 'TikTok account'),
    account('instagram', 'Instagram account'),
    {
      id: 'postiz',
      label: 'Postiz connected',
      done: accounts.length > 0 && connected === accounts.length,
      detail: accounts.length ? `${connected} of ${accounts.length} connected` : 'no accounts yet',
    },
    {
      id: 'closeup',
      label: 'Close-up shot ready',
      done: c.setup?.closeup === true,
      detail: c.setup?.closeup === true ? 'ready' : 'not generated yet',
    },
    { id: 'live', label: 'Live', done: c.status === 'live', detail: c.status === 'live' ? 'posting' : c.status },
  ];
  const done = items.filter((i) => i.done).length;
  return { items, done, total: items.length, ready: items.slice(0, 4).every((i) => i.done) };
}

export interface ChannelSlot {
  platform: 'instagram' | 'tiktok';
  /** The account's row of v_channels (today's ChannelPanel), or null: it does not exist yet. */
  channel: Channel | null;
  /** The handle planned for an account that does not exist yet. */
  planned: string | null;
}

/** The two channel slots of a character, in the order the Channels page always sorted them (by platform name). */
export function channelSlots(character: Pick<Character, 'slug' | 'setup'>, channels: ReadonlyArray<Channel>): ChannelSlot[] {
  return (['instagram', 'tiktok'] as const).map((platform) => ({
    platform,
    channel: channels.find((c) => c.character_slug === character.slug && c.platform === platform) ?? null,
    planned: character.setup?.planned_handles?.[platform] ?? null,
  }));
}

// ---- the per-character pipeline -----------------------------------------------------------------

export const PIPELINE_LIMITS = { proposed: 6, production: 8, waiting: 8, posted: 5 } as const;
/** Clip states between "planned" and "awaiting approval": what is being made. */
export const IN_PRODUCTION_STATES: ReadonlyArray<string> = [
  'planned', 'generating', 'gen_failed', 'generated', 'qa_failed', 'qa_passed', 'mastered',
];
const FAILED_STATES: ReadonlyArray<string> = ['gen_failed', 'qa_failed'];

export interface ProposedItem {
  id: string;
  hook: string | null;
  score: number | null;
  platform: string;
  creator: string | null;
  url: string;
  status: 'new' | 'approved' | 'analysed';
  /** Held by the standing rule (needs an untested capability). */
  held: boolean;
  ownerMode: OwnerMode | null;
  ownerPresence: OwnerPresence | null;
  ownerNote: string | null;
  /** Only a pick still waiting for the owner can be made from the sheet. */
  canMakeIt: boolean;
  /** The whole pick, for the sheet (null for one already decided). */
  pick: ViralPick | null;
}
export interface ProductionItem {
  id: string;
  hook: string | null;
  state: string;
  failed: boolean;
  createdAt: string;
  credits: number | null;
}
export interface WaitingItem {
  id: string;
  hook: string | null;
  kind: 'awaiting_approval' | 'scheduled';
  /** The slot it goes out at (London time on screen), or null when unknown. */
  at: string | null;
  platforms: string[];
  blocked: string | null;
}
export interface PostedItem {
  id: string;
  hook: string | null;
  postedAt: string | null;
  platforms: string[];
  views: number | null;
  outlierX: number | null;
}
export interface Stage<T> {
  items: T[];
  /** Everything in the stage; `items` is capped (PIPELINE_LIMITS). */
  total: number;
}
export type StageId = 'proposed' | 'production' | 'waiting' | 'posted';
export interface Pipeline {
  proposed: Stage<ProposedItem>;
  production: Stage<ProductionItem>;
  waiting: Stage<WaitingItem>;
  posted: Stage<PostedItem>;
  /** The first stage with anything in it, in pipeline order (the one the page opens); null when all are empty. */
  firstOpen: StageId | null;
}

const uniqueSorted = (xs: ReadonlyArray<string>) => [...new Set(xs)].sort();
const ts = (iso: string | null | undefined) => (iso ? Date.parse(iso) : Number.NaN);
const byScoreThenAge = (a: { score: number | null; created: string }, b: { score: number | null; created: string }) => {
  const an = a.score == null;
  const bn = b.score == null;
  if (an !== bn) return an ? 1 : -1;
  return (b.score ?? 0) - (a.score ?? 0) || ts(a.created) - ts(b.created);
};

/**
 * What one character has in flight, from the data the studio already loads: its picks waiting or approved
 * (Proposed), its clips being made (In production), the ones waiting for the owner or booked (Waiting /
 * scheduled) and the last posted ones (Posted). Pure: stage membership by state, ordering and limits live here.
 */
export function pipelineFor(slug: string, data: Pick<Snapshot, 'picks' | 'history' | 'queue' | 'library'>): Pipeline {
  const asItem = (row: ViralPick | PickHistory, pick: ViralPick | null): ProposedItem => ({
    id: row.id,
    hook: row.hook,
    score: row.total_score,
    platform: row.platform,
    creator: row.creator_handle,
    url: row.url,
    status: row.status as ProposedItem['status'],
    held: pick?.hold_reason != null,
    ownerMode: row.owner_mode ?? null,
    ownerPresence: row.owner_presence ?? null,
    ownerNote: row.owner_note ?? null,
    canMakeIt: row.status === 'new',
    pick,
  });
  // waiting for the owner first, then the approved ones; inside each group by score (unscored last), then oldest
  const proposedRows: Array<{ row: ViralPick | PickHistory; pick: ViralPick | null }> = [
    ...data.picks.filter((p) => p.character_slug === slug && p.status === 'new').map((p) => ({ row: p, pick: p })),
    ...data.history
      .filter((h) => h.character_slug === slug && (h.status === 'approved' || h.status === 'analysed'))
      .map((h) => ({ row: h, pick: null })),
  ];
  const proposedAll = proposedRows
    .sort(
      (a, b) =>
        Number(a.row.status !== 'new') - Number(b.row.status !== 'new') ||
        byScoreThenAge({ score: a.row.total_score, created: a.row.created_at }, { score: b.row.total_score, created: b.row.created_at }),
    )
    .map(({ row, pick }) => asItem(row, pick));

  const mine = (c: { character_slug: string }) => c.character_slug === slug;
  const productionAll = data.library
    .filter((c) => mine(c) && IN_PRODUCTION_STATES.includes(c.state))
    .sort((a, b) => ts(b.created_at) - ts(a.created_at))
    .map((c: LibraryClip): ProductionItem => ({
      id: c.id, hook: c.hook, state: c.state, failed: FAILED_STATES.includes(c.state), createdAt: c.created_at, credits: c.cost_credits,
    }));

  const awaiting = data.queue
    .filter(mine)
    .sort((a, b) => ts(a.created_at) - ts(b.created_at))
    .map((c: QueueClip): WaitingItem => ({
      id: c.id, hook: c.hook, kind: 'awaiting_approval', at: c.next_slot, platforms: uniqueSorted(c.targets.map((t) => t.platform)),
      blocked: c.blocked_reason,
    }));
  const scheduled = data.library
    .filter((c) => mine(c) && (c.state === 'scheduled' || c.state === 'approved'))
    .map((c: LibraryClip): WaitingItem => {
      const live = c.posts.filter((p) => p.status === 'scheduled' || p.status === 'posting');
      const slots = (live.length ? live : c.posts).map((p) => p.scheduled_for).sort();
      return {
        id: c.id, hook: c.hook, kind: 'scheduled', at: slots[0] ?? null, platforms: uniqueSorted(c.posts.map((p) => p.platform)), blocked: null,
      };
    })
    .sort((a, b) => (Number.isNaN(ts(a.at)) ? Infinity : ts(a.at)) - (Number.isNaN(ts(b.at)) ? Infinity : ts(b.at)));
  const waitingAll = [...awaiting, ...scheduled];

  const postedAll = data.library
    .filter((c) => mine(c) && c.state === 'posted')
    .sort((a, b) => ts(b.posted_at ?? b.created_at) - ts(a.posted_at ?? a.created_at))
    .map((c: LibraryClip): PostedItem => ({
      id: c.id, hook: c.hook, postedAt: c.posted_at, platforms: uniqueSorted(c.platforms), views: c.views, outlierX: c.outlier_x,
    }));

  const stage = <T,>(all: T[], limit: number): Stage<T> => ({ items: all.slice(0, limit), total: all.length });
  const out = {
    proposed: stage(proposedAll, PIPELINE_LIMITS.proposed),
    production: stage(productionAll, PIPELINE_LIMITS.production),
    waiting: stage(waitingAll, PIPELINE_LIMITS.waiting),
    posted: stage(postedAll, PIPELINE_LIMITS.posted),
  };
  const firstOpen = (['proposed', 'production', 'waiting', 'posted'] as const).find((k) => out[k].total > 0) ?? null;
  return { ...out, firstOpen };
}

// ---- the "Make it" sheet ----------------------------------------------------------------------------

/** The sheet's note limit; the database refuses more (decide_pick, migration 0007). */
export const NOTE_MAX = 280;

export interface MakeItChoice {
  /** A character slug, 'both', or null while nothing is chosen. */
  character: string | null;
  note: string;
  /** 'analyst' = the analyst decides (nothing is sent). */
  mode: 'analyst' | OwnerMode;
  /** His part in a Drop-in; only sent with mode 'dropin'. */
  presence: OwnerPresence;
}

export type MakeItPayload =
  | { ok: true; characterSlug: string; extras: Required<DecideExtras>; summary: string }
  | { ok: false; reason: string };

/**
 * What Approve sends for the sheet's choices: the chosen character (Both = the pick's own character plus the
 * other one as also_character, one clip each), the trimmed note (blank = none, 280 at most), the mode, and
 * his part only for a Drop-in. The database validates the same things again.
 */
export function makeItPayload(
  choice: MakeItChoice,
  ctx: { pickCharacter: string | null; characters: ReadonlyArray<string>; names?: Readonly<Record<string, string>> },
): MakeItPayload {
  const nameOf = (slug: string) => ctx.names?.[slug] ?? slug.charAt(0).toUpperCase() + slug.slice(1);
  if (!choice.character) return { ok: false, reason: 'Choose a character first' };
  const note = choice.note.trim();
  if (note.length > NOTE_MAX) return { ok: false, reason: `The note is limited to ${NOTE_MAX} characters (now ${note.length})` };

  let characterSlug: string;
  let also: string | null = null;
  if (choice.character === 'both') {
    if (ctx.characters.length !== 2) return { ok: false, reason: 'Both needs exactly two characters' };
    characterSlug = ctx.pickCharacter && ctx.characters.includes(ctx.pickCharacter) ? ctx.pickCharacter : ctx.characters[0];
    also = ctx.characters.find((c) => c !== characterSlug) ?? null;
  } else {
    if (!ctx.characters.includes(choice.character)) return { ok: false, reason: `Unknown character ${choice.character}` };
    characterSlug = choice.character;
  }
  return {
    ok: true,
    characterSlug,
    extras: {
      alsoCharacter: also,
      ownerNote: note || null,
      ownerMode: choice.mode === 'analyst' ? null : choice.mode,
      ownerPresence: choice.mode === 'dropin' ? choice.presence : null,
    },
    summary: also
      ? `Approved for ${nameOf(characterSlug)} and ${nameOf(also)}: one clip each`
      : `Approved for ${nameOf(characterSlug)}: it joins the production queue`,
  };
}

/** Where Tab lands inside a dialog with `count` focusable elements: wraps; -1 (outside) enters at the first or last. */
export function tabIndexAfter(current: number, count: number, shift: boolean): number {
  if (count <= 0) return -1;
  if (current < 0) return shift ? count - 1 : 0;
  return (current + (shift ? -1 : 1) + count) % count;
}

// ---- the Scanner ----------------------------------------------------------------------------------------

/** A run that has started and not finished is "stalled" from this age on (the daily run takes well under an hour). */
export const SCAN_STALL_MS = 3 * 3_600_000;
/** vidIQ credits per month of the owner's plan (config/scan.json budget.vidiq_monthly_credits). */
export const VIDIQ_MONTHLY_CREDITS = 150;
/** London weekdays the daily run scans on (the daily-run skill: at most 4 a week). */
export const SCAN_DAYS: ReadonlyArray<string> = ['Tue', 'Thu', 'Sat', 'Sun'];

export interface ScanNumbers {
  queries: string[];
  outliers: number;
  picks_added: number;
  auto_approved: number;
  held: number;
  skipped: number;
  vidiq_credits: number;
}
export interface ScannerStatus {
  state: 'scanning' | 'stalled' | 'finished' | 'none';
  headline: string;
  tone: 'live' | 'alert' | 'neutral' | 'muted';
  /** When the run in progress (or stalled) started. */
  startedAt: string | null;
  /** The last finished run that scanned, with its numbers. */
  last: { at: string; status: string; scan: ScanNumbers } | null;
  /** vidIQ credits the last scan's run used. */
  creditsRun: number | null;
  /** vidIQ credits used this London month, against `creditsLimit`. */
  creditsMonth: number;
  creditsLimit: number;
}

const count = (v: unknown) => (typeof v === 'number' && Number.isFinite(v) && v >= 0 ? v : 0);
const runCredits = (d: RunRow['details']) => (d?.scan ? count(d.scan.vidiq_credits) : count(d?.vidiq_credits));
const scanNumbers = (scan: ScanDetails): ScanNumbers => ({
  queries: Array.isArray(scan.queries) ? scan.queries.filter((q): q is string => typeof q === 'string') : [],
  outliers: count(scan.outliers),
  picks_added: count(scan.picks_added),
  auto_approved: count(scan.auto_approved),
  held: count(scan.held),
  skipped: count(scan.skipped),
  vidiq_credits: count(scan.vidiq_credits),
});
const RUN_ENDED: Record<string, string> = { ok: 'ok', budget_stop: 'stopped on the budget cap', error: 'failed' };

/**
 * The Scanner card's state from the run log (studio.runs): a daily run that started and has not finished is
 * "Scanning now" (stalled from 3 hours on), else the last finished run that scanned, else "No scan yet". A run
 * writes an open row first and a finished one with the same start last, so the newest daily row decides, and a
 * finished row beats an open one with the same start. Credits are summed over this London month.
 */
export function scannerStatus(runs: ReadonlyArray<RunRow>, now: number): ScannerStatus {
  const daily = runs
    .filter((r) => r.kind === 'daily')
    .sort((a, b) => ts(b.started_at) - ts(a.started_at) || Number(b.finished_at != null) - Number(a.finished_at != null));
  const latest = daily[0];
  const lastScan = daily.find((r) => r.finished_at != null && r.details?.scan);
  const last = lastScan
    ? { at: lastScan.finished_at!, status: lastScan.status, scan: scanNumbers(lastScan.details!.scan!) }
    : null;
  const month = londonDayKey(now).slice(0, 7);
  const creditsMonth = daily
    .filter((r) => londonDayKey(r.started_at).slice(0, 7) === month)
    .reduce((sum, r) => sum + runCredits(r.details), 0);
  const base = { last, creditsRun: last ? last.scan.vidiq_credits : null, creditsMonth, creditsLimit: VIDIQ_MONTHLY_CREDITS };

  if (latest && latest.finished_at == null) {
    const stalled = now - ts(latest.started_at) >= SCAN_STALL_MS;
    return stalled
      ? { ...base, state: 'stalled', headline: 'Scan stalled: the last run never finished', tone: 'alert', startedAt: latest.started_at }
      : { ...base, state: 'scanning', headline: 'Scanning now', tone: 'live', startedAt: latest.started_at };
  }
  if (last) {
    const ended = RUN_ENDED[last.status] ?? last.status;
    return {
      ...base, state: 'finished', startedAt: null, tone: last.status === 'error' ? 'alert' : 'neutral',
      headline: `Last scan ${londonDate(last.at)} ${londonTime(last.at)} · ${ended}`,
    };
  }
  return { ...base, state: 'none', headline: 'No scan yet', tone: 'muted', startedAt: null };
}

/** The next scheduled scan: the first 08:00 London after `now` on a scan day (Tue, Thu, Sat, Sun). */
export function nextScanAt(now: number): string {
  const [y, m, d] = londonDayKey(now).split('-').map(Number);
  for (let i = 0; i < 9; i++) {
    const day = new Date(Date.UTC(y, m - 1, d + i)).toISOString().slice(0, 10);
    const iso = londonWallToIso(`${day}T08:00`);
    if (Date.parse(iso) > now && SCAN_DAYS.includes(londonWeekday(iso))) return iso;
  }
  throw new Error('no scan day within nine days');
}

/** "Next scan Thu 8 Oct 08:00", or the static rule until a character is live (the schedule has no backend yet). */
export function nextScanLabel(now: number, anyLive: boolean): string {
  if (!anyLive) return 'Not scheduled yet: scans start when a character goes live (Tue, Thu, Sat and Sun at 08:00 London)';
  const at = nextScanAt(now);
  return `Next scan ${londonDate(at)} ${londonTime(at)}`;
}
