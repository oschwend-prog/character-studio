import { ageDays, pickVelocity } from './analyst';
import { londonDate, londonDayKey, londonTime, londonWallToIso, londonWeekday } from './format';
import type {
  Channel, Character, CharacterTraits, ClipFile, DecideExtras, LibraryClip, OwnerMode, OwnerMusic, OwnerPresence,
  Pick as ViralPick, PickHistory, QueueClip, RunRow, ScanDetails, Snapshot, Tier, TraitProp,
} from './types';
import { SCAN_BUDGET, TIER_RULES } from './scanConfig';

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
  /** The owner's gadgets & jewellery for this video. */
  ownerProps: string[];
  /** The tier (the analyst's, else derived) and its owner-facing label. */
  tier: Tier;
  tierLabel: string;
  /** Which scan theme it matched (null = none recorded). */
  theme: string | null;
  /** The picture to show (an image, or a placeholder tile when there is none). */
  thumb: ThumbSpec;
  /** What `thumbFor` was given, so the component can fall back on its own when the image fails to load. */
  thumbSource: Parameters<typeof thumbFor>[0];
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
export function pipelineFor(
  slug: string,
  data: Pick<Snapshot, 'picks' | 'history' | 'queue' | 'library'>,
  now: number = Date.now(),
): Pipeline {
  const asItem = (row: ViralPick | PickHistory, pick: ViralPick | null): ProposedItem => {
    const tier = tierOf(row, now).tier;
    return {
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
      ownerProps: row.owner_props ?? [],
      tier,
      tierLabel: TIER_LABELS[tier],
      theme: row.theme ?? null,
      thumb: thumbFor(row),
      thumbSource: {
        thumbnail_url: row.thumbnail_url, preview_url: row.preview_url, platform: row.platform, creator_handle: row.creator_handle,
        hook: row.hook, url: row.url,
      },
      canMakeIt: row.status === 'new',
      pick,
    };
  };
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
  /** "Gadgets & jewellery": the traits chips picked (their names); with `customProp`, at most PROPS_MAX in all. */
  props?: string[];
  /** The one free-text chip, at most PROP_MAX_CHARS characters; blank = none. */
  customProp?: string;
  /** Where the music comes from; undefined or the mode's default sends nothing (the daily run's default applies). */
  music?: OwnerMusic;
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
  ctx: {
    pickCharacter: string | null;
    characters: ReadonlyArray<string>;
    names?: Readonly<Record<string, string>>;
    /** The pick being made (only here for symmetry with the sheet: an attached clip is optional, nothing blocks). */
    pick?: { gallery?: boolean | null; owner_clip_path?: string | null };
    attachedPath?: string | null;
  },
): MakeItPayload {
  const nameOf = (slug: string) => ctx.names?.[slug] ?? slug.charAt(0).toUpperCase() + slug.slice(1);
  if (!choice.character) return { ok: false, reason: 'Choose a character first' };
  const note = choice.note.trim();
  if (note.length > NOTE_MAX) return { ok: false, reason: `The note is limited to ${NOTE_MAX} characters (now ${note.length})` };
  const props = gadgetList(choice.props ?? [], choice.customProp ?? '');
  if (!props.ok) return { ok: false, reason: props.reason };
  if (choice.mode === 'recreate' && choice.music === 'original') return { ok: false, reason: RECREATE_NO_ORIGINAL };

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
      ownerProps: props.items.length ? props.items : null,
      // only a choice that differs from the default is sent: the default (original for a Drop-in, ai_beat for a Recreate) is what the daily run does anyway
      ownerMusic: choice.music && choice.music !== defaultMusicForMode(choice.mode) ? choice.music : null,
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
export const VIDIQ_MONTHLY_CREDITS: number = SCAN_BUDGET.vidiq_monthly_credits;
/** London weekdays the daily run scans on: one Instagram + TikTok search each weekday (config/scan.json budget.scan_days). */
export const SCAN_DAYS: ReadonlyArray<string> = SCAN_BUDGET.scan_days;

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

/** The next scheduled scan: the first 08:00 London after `now` on a scan day (Mon to Fri). */
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
  if (!anyLive) return 'Not scheduled yet: scans start when a character goes live (Monday to Friday at 08:00 London)';
  const at = nextScanAt(now);
  return `Next scan ${londonDate(at)} ${londonTime(at)}`;
}

// ---- the pick card: tier, theme, picture, gadgets, music, estimate (migration 0008) --------------------------------

export const TIERS: ReadonlyArray<Tier> = ['iconic', 'viral_now', 'rising', 'gallery'];
/** The owner's keys and labels, in the order the Picks page groups them. */
export const TIER_LABELS: Record<Tier, string> = {
  iconic: 'Broke the internet',
  viral_now: 'Viral now',
  rising: 'Up and coming',
  gallery: 'Ready to drop in',
};
export const TIER_HINTS: Record<Tier, string> = {
  iconic: 'Everyone knows it: a famous meme, dance or scene, 6 months to years old (or 50M+ views), evergreen',
  viral_now: 'Peaking now: a big outlier, or climbing at 100K+ views a day',
  rising: 'Early and climbing fast: catch it before the peak',
  gallery: 'A clip from Higgsfield’s Genjutsu gallery: already clean and trimmed, a backup when nothing real fits',
};
const isTier = (v: unknown): v is Tier => typeof v === 'string' && (TIERS as ReadonlyArray<string>).includes(v);

export interface TierInput {
  tier?: string | null;
  gallery?: boolean | null;
  outlier_x: number | null;
  posted_at?: string | null;
  /** The views at filing time; with the age they give the velocity. */
  views?: number | null;
  /** Views per day, stored when the pick was filed; wins over views / age. */
  velocity?: number | null;
}

/**
 * The tier of a pick the analyst did not tier (mirrors studio.favorites.default_tier; both read parity-cases.json, and
 * config/scan.json `tier_rules` holds the numbers). In this order: a gallery clip is `gallery`; older than 180 days or
 * 50M views or more is `iconic`; posted within 21 days with an outlier of 20 or more, or at 100K views a day or more,
 * is `viral_now`; posted within 7 days with an outlier of 5 or more is `rising`; anything else is `viral_now` up to 30
 * days old and `iconic` after that (an unknown post date is `viral_now`).
 */
export function defaultTier(p: Pick<TierInput, 'gallery' | 'outlier_x' | 'posted_at' | 'views' | 'velocity'>, now: number): Tier {
  if (p.gallery) return 'gallery';
  const r = TIER_RULES;
  const age = ageDays(p.posted_at, now);
  const x = typeof p.outlier_x === 'number' && Number.isFinite(p.outlier_x) ? p.outlier_x : null;
  const views = typeof p.views === 'number' && Number.isFinite(p.views) ? p.views : null;
  if ((age != null && age > r.iconic_min_age_days) || (views != null && views >= r.iconic_min_views)) return 'iconic';
  if (age == null) return 'viral_now';
  const velocity = pickVelocity({ velocity: p.velocity, views: views, posted_at: p.posted_at }, now);
  if (age <= r.viral_now_max_age_days && ((x != null && x >= r.viral_now_min_outlier) || (velocity != null && velocity >= r.viral_now_min_velocity_per_day))) {
    return 'viral_now';
  }
  if (age <= r.rising_max_age_days && x != null && x >= r.rising_min_outlier) return 'rising';
  return age <= r.fallback_viral_now_max_age_days ? 'viral_now' : 'iconic';
}

/** The analyst's tier when it set one, else the derived one (`derived` says which). */
export function tierOf(p: TierInput, now: number): { tier: Tier; derived: boolean } {
  return isTier(p.tier) ? { tier: p.tier, derived: false } : { tier: defaultTier(p, now), derived: true };
}

export interface PickCardLike extends TierInput {
  id: string;
  character_slug: string | null;
  total_score: number | null;
  created_at: string;
  theme?: string | null;
}
export interface TierGroup<P> {
  tier: Tier;
  label: string;
  picks: P[];
}
export interface ThemeGroup<P> {
  /** null = no theme recorded. */
  theme: string | null;
  label: string;
  picks: P[];
}
export interface PickSection<P> {
  /** null = the section of picks that belong to no seeded character yet. */
  slug: string | null;
  name: string;
  /** Every pick of the section, in rank order (real clips by score, then the gallery ones). */
  picks: P[];
  tiers: TierGroup<P>[];
  themes: ThemeGroup<P>[];
}
export const UNASSIGNED_NAME = 'Unassigned / Outsider (later)';
export const NO_THEME = 'No theme';

/**
 * Rank order of one character's picks (owner priority 2026-10-05: real scanned viral clips first, the Genjutsu
 * gallery is the backup): everything but the gallery tier by total score (unscored last, older first on ties),
 * then the gallery ones the same way.
 */
export function rankPicks<P extends PickCardLike>(picks: ReadonlyArray<P>, now: number): P[] {
  const gallery = (p: P) => Number(tierOf(p, now).tier === 'gallery');
  return [...picks].sort(
    (a, b) =>
      gallery(a) - gallery(b) ||
      Number(a.total_score == null) - Number(b.total_score == null) ||
      (b.total_score ?? 0) - (a.total_score ?? 0) ||
      Date.parse(a.created_at) - Date.parse(b.created_at) ||
      a.id.localeCompare(b.id),
  );
}

/** How many picks each tier chip stands for (`all` = every pick). */
export function tierCounts(picks: ReadonlyArray<TierInput>, now: number): Record<Tier | 'all', number> {
  const out: Record<Tier | 'all', number> = { all: picks.length, iconic: 0, viral_now: 0, rising: 0, gallery: 0 };
  for (const p of picks) out[tierOf(p, now).tier] += 1;
  return out;
}

/**
 * The Picks page's structure: one section per character of the roster (always there, empty or not), then an
 * "Unassigned / Outsider (later)" section when some pick belongs to nobody seeded. Each section holds its picks in
 * `rankPicks` order, grouped by tier (Broke the internet, Viral now, Up and coming, Ready to drop in; empty
 * groups left out) and by theme (the best real clip's score first, themes of gallery clips only after them, "No
 * theme" last). `character` limits it to one character's section (no unassigned one); `tier` keeps one tier.
 */
export function groupPicksByCharacter<P extends PickCardLike>(
  picks: ReadonlyArray<P>,
  roster: ReadonlyArray<{ slug: string; name: string }>,
  opts: { now: number; character?: string | null; tier?: Tier | 'all' | null },
): PickSection<P>[] {
  const { now } = opts;
  const known = new Set(roster.map((c) => c.slug));
  const only = opts.character && opts.character !== 'all' && known.has(opts.character) ? opts.character : null;
  const wantTier = opts.tier && opts.tier !== 'all' ? opts.tier : null;
  const kept = picks.filter((p) => !wantTier || tierOf(p, now).tier === wantTier);

  const section = (slug: string | null, name: string, mine: P[]): PickSection<P> => {
    const ranked = rankPicks(mine, now);
    const tiers = TIERS.map((tier) => ({ tier, label: TIER_LABELS[tier], picks: ranked.filter((p) => tierOf(p, now).tier === tier) }))
      .filter((g) => g.picks.length > 0);
    const byTheme = new Map<string | null, P[]>();
    for (const p of ranked) {
      const key = p.theme?.trim() || null;
      byTheme.set(key, [...(byTheme.get(key) ?? []), p]);
    }
    const best = (g: P[]) => {
      const real = g.filter((p) => tierOf(p, now).tier !== 'gallery');
      return { real: real.length > 0, score: Math.max(...(real.length ? real : g).map((p) => p.total_score ?? -1)) };
    };
    const themes = [...byTheme.entries()]
      .map(([theme, list]) => ({ theme, label: theme ?? NO_THEME, picks: list, ...best(list) }))
      .sort(
        (a, b) =>
          Number(a.theme == null) - Number(b.theme == null) ||
          Number(!a.real) - Number(!b.real) ||
          b.score - a.score ||
          a.label.localeCompare(b.label),
      )
      .map(({ theme, label, picks: list }) => ({ theme, label, picks: list }));
    return { slug, name, picks: ranked, tiers, themes };
  };

  const out = roster
    .filter((c) => !only || c.slug === only)
    .map((c) => section(c.slug, c.name, kept.filter((p) => p.character_slug === c.slug)));
  if (!only) {
    const orphans = kept.filter((p) => !p.character_slug || !known.has(p.character_slug));
    if (orphans.length) out.push(section(null, UNASSIGNED_NAME, orphans));
  }
  return out;
}

// ---- the picture on a card -------------------------------------------------------------------------------------

export interface ThumbSpec {
  /** `image` when a usable thumbnail URL is known and has not failed to load, else a platform-colour tile. */
  kind: 'image' | 'placeholder';
  src: string | null;
  /** An https video the card can play muted and looping on tap (a Genjutsu preset's preview). */
  preview: string | null;
  /** 16:9 pictures (YouTube) are letterboxed inside the 9:16 frame. */
  aspect: '9:16' | '16:9';
  alt: string;
  platform: string;
  /** TT / IG / YT: the placeholder's monogram. */
  code: string;
  handle: string | null;
  /** The original video, for the "View original" link; null for a gallery clip (it has no page). */
  original: string | null;
}

const httpsUrl = (value: unknown): URL | null => {
  if (typeof value !== 'string' || !value.trim() || /\s/.test(value.trim())) return null;
  try {
    const u = new URL(value.trim());
    return u.protocol === 'https:' && u.hostname ? u : null;
  } catch {
    return null;
  }
};
const VIDEO_SUFFIX = /\.(mp4|webm|mov|m4v)$/i;
const PLATFORM_CODE: Record<string, string> = { tiktok: 'TT', instagram: 'IG', youtube: 'YT', higgsfield: 'HF' };

/**
 * Which picture a pick shows: its thumbnail (an https image URL a tool returned, or an inline data: image, as the demo
 * uses) unless it is missing, malformed, or `imageFailed` (platform CDN links expire), then a tidy placeholder tile
 * with the platform, the creator handle and a "View original" link. A valid https `preview_url` (a video) makes
 * the picture tappable either way. We never fetch or rehost the media: only the URL a tool already returned.
 */
export function thumbFor(
  p: { thumbnail_url?: string | null; preview_url?: string | null; platform: string; creator_handle: string | null; hook: string | null; url: string },
  opts: { imageFailed?: boolean } = {},
): ThumbSpec {
  const https = httpsUrl(p.thumbnail_url);
  const inline = typeof p.thumbnail_url === 'string' && /^data:image\//i.test(p.thumbnail_url) ? p.thumbnail_url : null;
  const src = https ? https.href : inline;
  const preview = httpsUrl(p.preview_url);
  const platform = PLATFORM_CODE[p.platform] ? p.platform : 'other';
  const name = p.hook ? `“${p.hook}”` : p.creator_handle ?? p.url;
  const where = PLATFORM_CODE[p.platform] ? ` on ${platformLabel(p.platform)}` : '';
  const by = p.creator_handle ? ` by ${p.creator_handle}` : '';
  const wide = p.platform === 'youtube' || /(^|\.)ytimg\.com$|(^|\.)youtube\.com$/.test(https?.hostname ?? '');
  const showImage = src != null && !opts.imageFailed;
  return {
    kind: showImage ? 'image' : 'placeholder',
    src: showImage ? src : null,
    preview: preview && VIDEO_SUFFIX.test(preview.pathname) ? preview.href : null,
    aspect: wide ? '16:9' : '9:16',
    alt: `${showImage ? 'Thumbnail' : 'Placeholder'} of ${name}${where}${by}`,
    platform,
    code: PLATFORM_CODE[p.platform] ?? '??',
    handle: p.creator_handle,
    original: httpsUrl(p.url)?.href ?? null,
  };
}
const platformLabel = (platform: string) =>
  ({ tiktok: 'TikTok', instagram: 'Instagram', youtube: 'YouTube', higgsfield: 'the Genjutsu gallery' })[platform] ?? platform;

// ---- the card's top line ---------------------------------------------------------------------------------------

const PART_NAME: Record<OwnerPresence, string> = { cameo: 'cameo', featured: 'featured', star: 'star' };

/**
 * "Drop-in · his part: featured" or "Recreate": what the video is, plainly. The owner's choice from the Make-it sheet
 * wins over the analyst's proposal; with neither it says the analyst decides.
 */
export function modeLine(p: { proposed_mode?: string | null; owner_mode?: OwnerMode | null; owner_presence?: OwnerPresence | null }): string {
  const mode = p.owner_mode ?? (p.proposed_mode === 'dropin' || p.proposed_mode === 'recreate' ? p.proposed_mode : null);
  if (mode === 'dropin') return `Drop-in · his part: ${PART_NAME[p.owner_presence ?? 'featured']}`;
  if (mode === 'recreate') return 'Recreate';
  return 'Analyst decides how to make it';
}

// ---- gadgets & jewellery -----------------------------------------------------------------------------------------

/** "Gadgets & jewellery": at most 3 items of 1-40 characters (decide_pick, migration 0008, refuses more). */
export const PROPS_MAX = 3;
export const PROP_MAX_CHARS = 40;

/** A traits card's props as chips: the name, and the viral job it does (null for a plain phrase). */
export function traitProps(traits: CharacterTraits | null | undefined): { name: string; job: string | null }[] {
  return (traits?.props ?? []).map((p: TraitProp) => (typeof p === 'string' ? { name: p, job: null } : { name: p.name, job: p.job }));
}

/**
 * The gadgets to send: the chips picked plus the free-text one, trimmed, blanks dropped, repeats (any case) once, in order.
 * Refused above PROPS_MAX items or when one is over PROP_MAX_CHARS, with the sentence the sheet shows.
 */
export function gadgetList(chips: ReadonlyArray<string>, custom: string): { ok: true; items: string[] } | { ok: false; reason: string } {
  const seen = new Set<string>();
  const items: string[] = [];
  for (const raw of [...chips, custom]) {
    const item = raw.trim();
    if (!item || seen.has(item.toLowerCase())) continue;
    if (item.length > PROP_MAX_CHARS) return { ok: false, reason: `“${item.slice(0, 20)}…” is longer than ${PROP_MAX_CHARS} characters` };
    seen.add(item.toLowerCase());
    items.push(item);
  }
  if (items.length > PROPS_MAX) return { ok: false, reason: `Pick at most ${PROPS_MAX} gadgets (now ${items.length})` };
  return { ok: true, items };
}

// ---- music ---------------------------------------------------------------------------------------------------------

/** Under the "Keep original audio" option (owner decision 2026-10-05, replacing the earlier warning). */
export const ORIGINAL_AUDIO_NOTE = 'If Instagram mutes a chart song, re-post with the song added in-app.';
export const RECREATE_NO_ORIGINAL = 'A Recreate has no original audio: choose the AI beat or add the song in the Instagram app';

/** Drop-ins keep the original clip audio by default; a Recreate keeps the beat of its own synthetic driver. */
export const DEFAULT_MUSIC: OwnerMusic = 'original';
export const MUSIC_OPTIONS: { id: OwnerMusic; name: string; help: string; note?: string }[] = [
  {
    id: 'original',
    name: 'Keep original audio (default)',
    help: 'The clip’s own sound comes through, loudness-matched. No beat to pay for.',
    note: ORIGINAL_AUDIO_NOTE,
  },
  { id: 'in_app', name: 'Add in Instagram app', help: 'The video goes out silent and you add the song while posting: the fallback if a post gets muted. No beat to pay for.' },
  { id: 'ai_beat', name: 'AI beat (+30)', help: 'Our own beat, made for this clip (about 30 credits more).' },
];

/** The music a mode starts on: the original audio for a Drop-in (or when the analyst decides), the AI beat for a Recreate. */
export function defaultMusicForMode(mode: 'analyst' | OwnerMode): OwnerMusic {
  return mode === 'recreate' ? 'ai_beat' : DEFAULT_MUSIC;
}

/** The options offered for a mode: a Recreate has no original audio, so it chooses between its AI beat and the in-app song. */
export function musicOptionsFor(mode: 'analyst' | OwnerMode): { id: OwnerMusic; name: string; help: string; note?: string }[] {
  if (mode !== 'recreate') return MUSIC_OPTIONS;
  return [
    { id: 'ai_beat', name: 'AI beat (default)', help: 'The beat of the synthetic driver this Recreate is made from: already paid for in its 160 credits.' },
    MUSIC_OPTIONS[1],
  ];
}

// ---- the estimate ------------------------------------------------------------------------------------------------

/** The numbers of studio.planning.estimate_credits; parity-cases.json holds the cases both sides must agree on. */
export const CREDITS = { recreate: 160, dropinPerSecond: 11, stills: 3, aiBeat: 30, defaultSeconds: 8 } as const;

/** Credits one clip is expected to cost: Recreate 160; a Drop-in ceil(seconds x 11) + 3 (+ 30 for an AI beat). */
export function estimateCredits(mode: OwnerMode, seconds: number = CREDITS.defaultSeconds, music: OwnerMusic = 'in_app'): number {
  if (mode === 'recreate') return CREDITS.recreate;
  const perSecond = Math.ceil(Math.round(seconds * CREDITS.dropinPerSecond * 1e6) / 1e6);
  return perSecond + CREDITS.stills + (music === 'ai_beat' ? CREDITS.aiBeat : 0);
}

/**
 * What the Make-it sheet shows for the chosen options: the credits per clip and in all ("Both" makes one clip each).
 * "Analyst decides" is priced as a Drop-in (the default for every video) and says what a Recreate would cost.
 */
export function sheetEstimate(c: {
  mode: 'analyst' | OwnerMode;
  music?: OwnerMusic;
  clips: number;
  /** A clip the daily run can drive a Drop-in with (an attached one, or a gallery preset); undefined = assume there is one. */
  usableSource?: boolean;
}): {
  perClip: number;
  total: number;
  label: string;
  note: string | null;
  /** What the daily run will make: dropin when a usable source exists, else recreate. */
  effective: OwnerMode;
} {
  const effective = effectiveMode(c.mode, c.usableSource ?? true);
  const wanted = c.music ?? defaultMusicForMode(effective);
  const music = musicOptionsFor(effective).some((o) => o.id === wanted) ? wanted : defaultMusicForMode(effective);
  const perClip = estimateCredits(effective, CREDITS.defaultSeconds, music);
  const total = perClip * Math.max(1, c.clips);
  const label = c.clips > 1 ? `≈ ${total} credits (${c.clips} clips of ≈ ${perClip})` : `≈ ${total} credits`;
  const note =
    c.mode !== 'recreate' && effective === 'recreate'
      ? noClipNote()
      : c.mode === 'analyst'
        ? `Priced as a Drop-in of ${CREDITS.defaultSeconds} s; if the analyst makes it as Recreate it is ${CREDITS.recreate} per clip.`
        : effective === 'dropin'
          ? `A Drop-in of ${CREDITS.defaultSeconds} s: Genjutsu is paid per second of the trimmed clip.`
          : 'A Recreate includes its own driver and beat.';
  return { perClip, total, label, note, effective };
}

/** Can the daily run drive a Drop-in with this pick: a Genjutsu gallery preset, or the owner's attached clip? */
export function hasUsableSource(pick: { gallery?: boolean | null; owner_clip_path?: string | null } | undefined, attachedPath?: string | null): boolean {
  if (!pick) return true; // nothing known: do not claim a Recreate
  return Boolean(pick.gallery || pick.owner_clip_path || attachedPath);
}

/**
 * The mode the daily run will really use. The owner's mode is stored as chosen; a Drop-in (or "analyst decides")
 * needs a usable source, and without one the pick is made automatically as a Recreate.
 */
export function effectiveMode(mode: 'analyst' | OwnerMode, usableSource: boolean): OwnerMode {
  return mode === 'recreate' ? 'recreate' : usableSource ? 'dropin' : 'recreate';
}

/** The line under the sheet's mode choice when a real clip has no file attached (owner decision 2026-10-05, section J). */
export function noClipNote(): string {
  return `No clip attached → it will be made automatically as a Recreate (≈${CREDITS.recreate} credits). Attach the clip to make it a true Drop-in (≈${estimateCredits('dropin')}).`;
}

// ---- attaching the owner's own clip ---------------------------------------------------------------------------------

export const CLIP_MAX_BYTES = 200 * 1024 * 1024;
export const CLIP_MAX_SECONDS = 60;
export const CLIP_HELP =
  'Best: a screen recording of the Reel/TikTok, or the creator’s own file. TikTok “Save video” adds a watermark we can’t use.';
const CLIP_EXTENSIONS = ['mp4', 'mov', 'm4v', 'webm'] as const;

/** The part of the check that needs no video element: a video by type or extension, not empty, at most 200 MB. */
export function checkClipBasics(file: Pick<ClipFile, 'name' | 'size' | 'type'>): { ok: true } | { ok: false; reason: string } {
  const ext = file.name.toLowerCase().split('.').pop() ?? '';
  const looksLikeVideo = file.type.toLowerCase().startsWith('video/') || (CLIP_EXTENSIONS as ReadonlyArray<string>).includes(ext);
  if (!looksLikeVideo) return { ok: false, reason: 'That is not a video file: choose an mp4 or mov' };
  if (!(file.size > 0)) return { ok: false, reason: 'That file is empty' };
  if (file.size > CLIP_MAX_BYTES) {
    return { ok: false, reason: `The clip is ${(file.size / 1024 / 1024).toFixed(0)} MB: the limit is ${CLIP_MAX_BYTES / 1024 / 1024} MB` };
  }
  return { ok: true };
}

/**
 * The file the owner chose for "Attach clip": a video (an iPhone camera-roll clip is video/quicktime or has no
 * type at all, so the extension counts too), at most 200 MB and 60 s. `durationS` is what a `<video>` element read
 * from it (null = it could not be read).
 */
export function validateClipFile(file: Pick<ClipFile, 'name' | 'size' | 'type'>, durationS: number | null): { ok: true } | { ok: false; reason: string } {
  const basics = checkClipBasics(file);
  if (!basics.ok) return basics;
  if (durationS == null || !Number.isFinite(durationS) || durationS <= 0) {
    return { ok: false, reason: 'This browser could not read that video: try an mp4 or mov' };
  }
  if (durationS > CLIP_MAX_SECONDS) {
    return { ok: false, reason: `The clip is ${Math.round(durationS)} s: the limit is ${CLIP_MAX_SECONDS} s. Trim it to the part we need` };
  }
  return { ok: true };
}

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

/** Where the upload goes: bucket `sources`, `owner/<pick id>/<timestamp>.<ext>` (what attach_clip and the storage policy accept). */
export function ownerClipPath(pickId: string, file: Pick<ClipFile, 'name' | 'type'>, now: number): string {
  if (!UUID.test(pickId)) throw new Error(`not a pick id: ${pickId}`);
  const named = file.name.toLowerCase().match(/\.([a-z0-9]+)$/)?.[1];
  const ext = (CLIP_EXTENSIONS as ReadonlyArray<string>).includes(named ?? '')
    ? named!
    : file.type.toLowerCase().includes('quicktime')
      ? 'mov'
      : 'mp4';
  return `owner/${pickId.toLowerCase()}/${Math.trunc(now)}.${ext}`;
}

// ---- the character switcher --------------------------------------------------------------------------------------------

export const CHARACTER_FILTER_KEY = 'oddeyes.character';

/** `all` or a roster slug; anything else is not a filter. */
export function parseCharacterFilter(value: unknown, known: ReadonlyArray<string>): string | null {
  return typeof value === 'string' && (value === 'all' || known.includes(value)) ? value : null;
}

/**
 * The choice the switcher opens on: a `?c=<slug>` deep link (from the page URL or the hash) wins, else what this
 * viewer chose last time, else `all`. Storage may be missing or throw (a private window, blocked site data): that is `all`.
 */
export function loadCharacterFilter(
  storage: Pick<Storage, 'getItem'> | null | undefined,
  query: string | URLSearchParams,
  known: ReadonlyArray<string>,
): string {
  const linked = parseCharacterFilter(new URLSearchParams(query).get('c'), known);
  if (linked) return linked;
  try {
    return parseCharacterFilter(storage?.getItem(CHARACTER_FILTER_KEY), known) ?? 'all';
  } catch {
    return 'all';
  }
}

/** Remember the choice for this viewer; false when storage is missing or refuses (nothing else depends on it). */
export function saveCharacterFilter(storage: Pick<Storage, 'setItem'> | null | undefined, value: string): boolean {
  try {
    if (!storage) return false;
    storage.setItem(CHARACTER_FILTER_KEY, value);
    return true;
  } catch {
    return false;
  }
}

/** The segmented control's options in the owner's order: each character, then All. */
export function characterFilterOptions(roster: ReadonlyArray<{ slug: string; name: string }>): { id: string; label: string }[] {
  return [...roster.map((c) => ({ id: c.slug, label: c.name })), { id: 'all', label: 'All' }];
}

// ---- the traits card -------------------------------------------------------------------------------------------------------

export interface TraitRow {
  key: keyof CharacterTraits;
  label: string;
  /** `text` is one phrase, `chips` a list. */
  kind: 'text' | 'chips';
  values: { text: string; hint?: string }[];
}

/** The Traits card's rows in reading order; a character with no card has none. */
export function traitRows(traits: CharacterTraits | null | undefined): TraitRow[] {
  if (!traits) return [];
  const text = (key: keyof CharacterTraits, label: string): TraitRow => ({ key, label, kind: 'text', values: [{ text: String(traits[key] ?? '') }] });
  const chips = (key: 'best_formats' | 'settings' | 'moves' | 'never', label: string): TraitRow => ({
    key, label, kind: 'chips', values: (traits[key] ?? []).map((t) => ({ text: t })),
  });
  const rows: TraitRow[] = [
    text('energy', 'Energy'),
    text('comedy', 'Comedy'),
    chips('best_formats', 'Best formats'),
    chips('settings', 'Settings'),
    chips('moves', 'Moves'),
    { key: 'props', label: 'Gadgets & jewellery', kind: 'chips', values: traitProps(traits).map((p) => ({ text: p.name, ...(p.job ? { hint: p.job } : {}) })) },
    text('music', 'Music'),
    chips('never', 'Never'),
  ];
  return rows.filter((r) => r.values.length > 0 && r.values.every((v) => v.text.trim()));
}
