// Row shapes of the studio views (supabase/migrations/0004_terminal_rpc.sql, 0007_characters_view.sql, 0008_dropin_first.sql, 0009_analyst.sql,
// 0010_tracker.sql, 0015_terminal_v3.sql: v_views_daily and the drop card's score and copy_of; 0016_hits.sql: v_hits and the drop
// card's keep). Numbers that Postgres
// returns as numeric/bigint may arrive as strings over PostgREST; `num()` in data.ts normalises them.

export type Platform = 'tiktok' | 'instagram';
export type PostStatus = 'scheduled' | 'posting' | 'posted' | 'failed' | 'needs_check';
export type ClipState =
  | 'planned' | 'generating' | 'gen_failed' | 'generated' | 'qa_failed' | 'qa_passed' | 'mastered'
  | 'awaiting_approval' | 'approved' | 'rejected' | 'scheduled' | 'posted' | 'dropped';

export interface TodayPost {
  post_id: string;
  clip_id: string;
  scheduled_for: string;
  status: PostStatus;
  hook: string | null;
  mode: 'dropin' | 'recreate';
  url: string | null;
}

export interface Channel {
  account_id: string;
  character_slug: string;
  character_name: string;
  character_status: string;
  platform: Platform;
  handle: string | null;
  connected: boolean;
  mode: 'approval' | 'auto';
  dropin_share: number;
  dropin_ratio: number;
  approved_posts: number;
  autopilot_min_approved: number;
  autopilot_unlocked: boolean;
  posts_posted: number;
  posts_scheduled: number;
  posts_problem: number;
  views_7d: number | null;
  follows: number | null;
  median_outlier_x: number | null;
  hit_rate: number | null;
  measured_clips: number;
  bar_status: string | null;
  next_slot: string | null;
  today_posts: TodayPost[];
}

export interface Target {
  account_id: string;
  platform: Platform;
  handle: string | null;
  mode: string;
}

export interface QueueClip {
  id: string;
  character_slug: string;
  character_name: string;
  mode: 'dropin' | 'recreate';
  state: ClipState;
  master_path: string | null;
  hook: string | null;
  caption: string | null;
  hashtags: string[];
  cost_credits: number | null;
  qa: { tech?: string; problems?: string[]; visual?: string; [k: string]: unknown };
  features: Record<string, unknown>;
  created_at: string;
  source_kind: string | null;
  source_url: string | null;
  source_credit: string | null;
  source_trend: string | null;
  targets: Target[];
  next_slot: string | null;
  pick_id: string | null;
  pick_url: string | null;
  /** Why it cannot be approved yet (migration 0005), or null. */
  blocked_reason: string | null;
  /** The line the owner pins under the post (features.first_comment, migration 0010); absent before 0010. */
  first_comment?: string | null;
}

export interface LibraryPost {
  post_id: string;
  platform: Platform;
  handle: string | null;
  status: PostStatus;
  scheduled_for: string;
  url: string | null;
  views: number | null;
  likes: number | null;
  comments: number | null;
  shares: number | null;
  saves: number | null;
  captured_at: string | null;
}

export interface LibraryClip {
  id: string;
  character_slug: string;
  character_name: string;
  mode: 'dropin' | 'recreate';
  state: ClipState;
  hook: string | null;
  caption: string | null;
  master_path: string | null;
  reject_reason: string | null;
  created_at: string;
  cost_credits: number | null;
  outlier_x: number | null;
  format_id: string | null;
  posts: LibraryPost[];
  platforms: string[];
  views: number | null;
  posted_at: string | null;
}

export interface CharacterSpend {
  slug: string;
  name: string;
  settled: number;
  reserved: number;
  committed: number;
}

export interface Budget {
  month: string;
  cap: number;
  kill_switch: boolean;
  settled: number;
  reserved: number;
  committed: number;
  day_of_month: number;
  days_in_month: number;
  projected: number;
  by_character: CharacterSpend[];
}

export interface HealthRow {
  kind: 'daily_run' | 'post' | 'budget';
  severity: 'critical' | 'warning';
  message: string;
  ref_id: string | null;
  since: string;
}

export interface Decision {
  decision: 'approve' | 'skip' | 'hold';
  by: 'owner' | 'analyst' | 'rule';
  reason: string | null;
  /** When it was decided (ISO): `fav decide` and, from migration 0011, decide_pick store it; older records lack it. */
  at?: string | null;
}

export interface Pick {
  id: string;
  url: string;
  platform: string;
  creator_handle: string | null;
  views: number | null;
  outlier_x: number | null;
  origin: 'scan' | 'owner';
  character_slug: string | null;
  character_name: string | null;
  intended_character: string | null;
  total_score: number | null;
  virality: number | null;
  reach: number | null;
  freshness: number | null;
  fit: number | null;
  feasibility: number | null;
  saturation: number | null;
  proposed_mode: string | null;
  hook: string | null;
  prop: string | null;
  concept: string | null;
  enhancement: string | null;
  needs: string | string[] | null;
  decision: Decision | null;
  hold_reason: string | null;
  note: string | null;
  status: string;
  created_at: string;
  /** What the owner said in the "Make it" sheet (migration 0007); null when nothing was said. */
  owner_note: string | null;
  owner_mode: OwnerMode | null;
  owner_presence: OwnerPresence | null;
  /**
   * The pick card of migration 0008. Optional on purpose: a row from a database that has not had 0008 yet lacks them,
   * and every reader treats absent like null.
   */
  owner_props?: string[] | null;
  owner_music?: OwnerMusic | null;
  /** Where the owner's own clip for a Drop-in sits in the `sources` bucket (owner/<pick id>/<file>), once attached. */
  owner_clip_path?: string | null;
  /** The analyst's tier; null = the terminal derives it (`defaultTier`). */
  tier?: Tier | null;
  /** Which of the character's scan themes it matched. */
  theme?: string | null;
  /** When the video was posted (ISO date or time): what the tier rule reads. */
  posted_at?: string | null;
  /** A Higgsfield Genjutsu gallery clip (preset or source kind). */
  gallery?: boolean | null;
  /** An https image URL a tool returned; never fetched or rehosted by us. */
  thumbnail_url?: string | null;
  /** An https video URL (a Genjutsu preset's preview) for the tap-to-play preview. */
  preview_url?: string | null;
  // The analyst's data (migration 0009): absent on a database that has not had it yet, and every reader treats absent like null.
  /** Views per day since posting, worked out when the pick was filed. */
  velocity?: number | null;
  /** Likes, comments, shares and saves, when vidIQ returned them. */
  engagement?: Engagement | null;
  /** Similar outliers found in the last 7 days (the saturation sub-score is worked out from it). */
  saturation_count?: number | null;
  /** 1-4 short phrases of the character's traits card the video matches. */
  trait_matches?: string[] | null;
  /** The analyst's reasoning, one paragraph. */
  why?: string | null;
  /** The local check of a fetched or attached clip. */
  analysis?: ClipAnalysis | null;
  // The long list (migration 0010): absent on a database that has not had it yet; every reader treats absent like null.
  /** 0-10: how instantly people know an iconic moment (only meaningful for tier iconic). */
  recognisability?: number | null;
  /** The famous original's views (an iconic moment's own video, which may not be the picked URL). */
  original_views?: number | null;
  original_url?: string | null;
  /** One line on the clip that would drive a Drop-in ("clean clip found", "needs a clean clip (recreate fallback)"). */
  source_status?: string | null;
  /** One line on the audio ("chart song: Instagram may mute it, fallback in-app"). */
  audio_risk?: string | null;
  /** The analyst's credit estimate; null = the terminal works it out (`estimateCredits`). */
  est_credits?: number | null;
  /** When it peaks ("24-31 Oct"). */
  season?: string | null;
  /** What to watch for, one short sentence each. */
  checks?: string[] | null;
  /** Clean clips that might drive a Drop-in. */
  source_candidates?: SourceCandidate[] | null;
}

/** A clean clip that might drive a Drop-in, as the analyst noted it (free keys; these are the usual ones). */
export interface SourceCandidate {
  id?: string;
  url?: string;
  views?: number | null;
  published?: string;
  why?: string;
  [k: string]: unknown;
}

/** What vidIQ returned about a video's reactions; any count may be absent. */
export interface Engagement {
  likes?: number;
  comments?: number;
  shares?: number;
  saves?: number;
}

/** The check of a clip (`proposal.analysis`, stored by `fav mark --analysis-file`): people, subject, camera, flags, best window, beat. */
export interface ClipAnalysis {
  people_count: number;
  main_subject?: string;
  camera: 'static' | 'handheld' | 'moving';
  watermark: boolean;
  overlay: boolean;
  /** A child is visible somewhere in the clip. Recorded only: children are fine, the star we replace must be an adult. */
  minors: boolean;
  best_window?: { start_s: number; end_s: number } | null;
  bpm?: number | null;
  notes?: string;
}

export interface PickHistory {
  id: string;
  url: string;
  platform: string;
  creator_handle: string | null;
  views: number | null;
  outlier_x: number | null;
  origin: 'scan' | 'owner';
  character_slug: string | null;
  character_name: string | null;
  total_score: number | null;
  hook: string | null;
  concept: string | null;
  decision: Decision | null;
  note: string | null;
  status: string;
  created_at: string;
  clip_id: string | null;
  clip_state: ClipState | null;
  owner_note: string | null;
  owner_mode: OwnerMode | null;
  owner_presence: OwnerPresence | null;
  owner_props?: string[] | null;
  owner_music?: OwnerMusic | null;
  owner_clip_path?: string | null;
  tier?: Tier | null;
  theme?: string | null;
  posted_at?: string | null;
  gallery?: boolean | null;
  thumbnail_url?: string | null;
  preview_url?: string | null;
  velocity?: number | null;
  engagement?: Engagement | null;
  saturation_count?: number | null;
  trait_matches?: string[] | null;
  why?: string | null;
  analysis?: ClipAnalysis | null;
  recognisability?: number | null;
  original_views?: number | null;
  original_url?: string | null;
  source_status?: string | null;
  audio_risk?: string | null;
  est_credits?: number | null;
  season?: string | null;
  checks?: string[] | null;
  source_candidates?: SourceCandidate[] | null;
}

/**
 * One row of v_tracker (migration 0010): an approved pick on its way to being posted. The pick's card, its newest clip,
 * that clip's latest post and the credits settled on the pick so far. Times are ISO strings.
 */
export interface TrackerRow {
  pick_id: string;
  character_slug: string | null;
  character_name: string | null;
  url: string;
  platform: string;
  creator_handle: string | null;
  views: number | null;
  outlier_x: number | null;
  tier: Tier | null;
  theme: string | null;
  concept: string | null;
  hook: string | null;
  thumbnail_url: string | null;
  preview_url: string | null;
  gallery: boolean | null;
  /** When the original video was posted (what the derived tier reads), not our post. */
  posted_at: string | null;
  velocity: number | null;
  proposed_mode: string | null;
  owner_mode: OwnerMode | null;
  owner_presence: OwnerPresence | null;
  owner_music: OwnerMusic | null;
  owner_clip_path: string | null;
  /** The pick's status: approved, analysed, queued or made. */
  status: string;
  decision: Decision | null;
  /** When the pick was approved: its decision record's `at`, else (an older record) its filing time (migration 0011). */
  approved_at: string;
  note: string | null;
  source_id: string | null;
  analysis: ClipAnalysis | null;
  /** Set when the clip could not be fetched (the pick is then made as a Recreate). */
  fetch_failed: { reason?: string; at?: string } | null;
  clip_id: string | null;
  clip_state: ClipState | null;
  clip_mode: 'dropin' | 'recreate' | null;
  /** The latest known moment the clip moved (its creation, a ledger entry, a post's claim): best effort. */
  clip_state_since: string | null;
  /** The reject reason, else the QA problems, else the QA error. */
  clip_failure: string | null;
  /** Credits settled on every clip of the pick so far. */
  credits_spent: number;
  post_id: string | null;
  post_status: PostStatus | null;
  post_scheduled_for: string | null;
  post_posted_at: string | null;
  post_url: string | null;
  post_error: string | null;
  /** The views of the post's latest metric snapshot. */
  latest_views: number | null;
  /** The clip's post text and the comment the owner pins: shown with Copy at Your OK and Scheduled. */
  caption: string | null;
  hashtags: string[] | null;
  first_comment: string | null;
  /** The decision record's checked time alone (migration 0011); null for an older record or before 0011. */
  decided_at?: string | null;
  /** A video the owner dropped (migration 0012: proposal.drop without the job's internals); null for a scan or Picks pick. */
  drop_card?: DropCard | null;
  /** When the owner tapped Make it (proposal.make_requested.at, migration 0012). */
  make_requested_at?: string | null;
}

/** Where a dropped video is ("Drop a video", 2026-10-06): studio.drop's states. */
export type DropState = 'uploading' | 'checking' | 'waiting' | 'ready' | 'blocked' | 'making' | 'made' | 'failed';

/** The owner's Adjust of a ready drop (sent with Make it; every field optional; checked again by the database and the CLI). */
export interface DropAdjust {
  /** Who is replaced, by position or clothes. */
  star?: string;
  part?: OwnerPresence;
  gadgets?: string[];
  hook?: string;
  start_s?: number;
  length_s?: number;
  /** The centre of the 9:16 crop of a landscape clip (0 left, 1 right); null = no crop. */
  crop_x?: number | null;
}

/** The drop card of a tracker row (v_tracker.drop_card): what the check found and what Make it will make. */
export interface DropCard {
  state: DropState;
  /** One line: why it is blocked, waiting or failed, or what a making job waits for. */
  reason?: string | null;
  at?: string;
  kind?: 'file' | 'link';
  source_id?: string;
  duration_s?: number;
  width?: number;
  height?: number;
  window?: { start_s: number; length_s: number };
  crop_x?: number | null;
  star?: { kind: 'person' | 'dog' | 'animal' | 'none'; body: 'biped' | 'quadruped'; description: string; x_center: number; full_body?: boolean };
  classic?: boolean;
  part?: OwnerPresence;
  gadgets?: string[];
  hooks?: string[];
  hook?: string;
  music?: OwnerMusic;
  seconds?: number;
  credits?: number;
  /** sources/owner/<pick id>/preview.jpg: five frames of the section (signed for the owner's browser). */
  preview_path?: string | null;
  adjust?: DropAdjust;
  requested?: { process?: string; make?: string };
  /** Owner 2026-10-06: his own recording or footage used with permission (true) or a downloaded clip (false, the default). For
   * reporting later: the generation never reads it. */
  own_footage?: boolean;
  /** Who chose the character (migration 0013): `owner` (never overridden) or `studio` (the Drop box's Recommend: the check moves
   * the drop to the character it recommends). Absent on a drop from before 0013: the owner's. */
  character_by?: 'owner' | 'studio';
  /** The check's recommendation (studio.drop): who of the live roster should replace the star, like for like, and one line why. */
  recommended?: DropRecommendation | null;
  /** When text or a watermark is on screen (the check's spans, padded): the section keeps clear of them, and so must the Adjust. */
  avoid?: DropAvoid[];
  /** The longest section Make it takes for this character: 16 s less what his kit adds before the dance (Reginald's pause: 15.6 s).
   * Written by the check; absent on a drop checked before that (16 s). */
  max_length_s?: number;
  /** The clip's score (terminal v3, studio.drop.drop_score): stored by a check that ends ready. Absent on a clip checked before
   * the score existed (until `studio drop recheck`), on a blocked or failed check, and while a version or a new character is
   * checked: every reader treats it as unscored (ranking.scoreOf), never as 0. */
  score?: DropScore | null;
  /** A version of another drop (terminal v3, "Use for another character"): the ROOT's pick id, also for a version of a version.
   * Absent on the root and on any drop that is no version. */
  copy_of?: string | null;
  /** The owner's Keep (set_drop_keep, migration 0016): retention never deletes a kept clip's file. Absent = not kept. */
  keep?: boolean;
  /** Filed by the hits job on its own (migration 0016, studio.hits.auto_file); absent on everything else. */
  auto_filed?: boolean;
  /** The hit the job filed it from: its id and lane (a character's slug, or `general`). */
  hit?: { id?: string; lane?: string } | null;
}

/** The clip score of the free check: total = round(10 x (0.6 x potential + 0.4 x swap)); reason = the potential's one line. */
export interface DropScore {
  /** 0-100: what the ranking sorts by. */
  total: number;
  /** 0-10: how likely the clip, with our character in it, gets views (Gemini, with the hit rules). */
  potential: number;
  /** 0-10: how easy the swap is (one person, full body, static camera, clear of text, sound, a classic). */
  swap: number;
  /** At most 80 characters: why it may get views. */
  reason: string;
}

export interface DropRecommendation {
  slug: string;
  /** At most 80 characters: "gym setting: Reginald's sweatband gag". */
  reason: string;
}

export interface DropAvoid {
  start_s: number;
  end_s: number;
  what: 'text' | 'watermark';
}

/** Virality category of a pick (`proposal.tier`): the keys and labels are the owner's (see TIER_LABELS in rules.ts). */
export type Tier = 'iconic' | 'viral_now' | 'rising' | 'gallery';
/** Where a Drop-in's music comes from (`proposal.owner_music`): the owner's per-video choice. */
export type OwnerMusic = 'in_app' | 'original' | 'ai_beat';

/** How to loop the character in (`proposal.owner_mode`); absent = the analyst decides. */
export type OwnerMode = 'dropin' | 'recreate';
/** How big his part is in a Drop-in (`proposal.owner_presence`). */
export type OwnerPresence = 'cameo' | 'featured' | 'star';

/** One account of a character, as v_characters lists it (0007). */
export interface CharacterAccount {
  platform: Platform;
  handle: string | null;
  /** A Postiz integration id is set (the same notion as Channel.connected). */
  has_postiz: boolean;
  mode: 'approval' | 'auto';
}

/** One gadget of a traits card: a phrase, or its name with the viral job it does. */
export type TraitProp = string | { name: string; job: string };

/** The character's trait card (refs.json `traits`, seeded into characters.setup.traits). */
export interface CharacterTraits {
  energy: string;
  comedy: string;
  best_formats: string[];
  settings: string[];
  moves: string[];
  props: TraitProp[];
  music: string;
  never: string[];
}

/** What `studio seed` writes from refs.json into characters.setup. */
export interface CharacterSetup {
  closeup?: boolean;
  planned_handles?: { tiktok?: string | null; instagram?: string | null };
  traits?: CharacterTraits | null;
  /** Higgsfield job ids of the character sheets, by body: the Genjutsu reference image next to the master. */
  sheets?: { biped?: string | null; quadruped?: string | null } | null;
  /** Who he replaces, like for like (the seed's copy of refs.json `swap.stars`, terminal v3): 'person', 'dog', 'animal'. Absent on
   * a character seeded before it: then only his bodies decide (studio.copy_drop). */
  stars?: string[] | null;
  /** The key migration 0013 read for the same list (`setup.swap.stars`); copy_drop still honours it after `stars`. */
  swap?: { stars?: string[] | null } | null;
}

/** One row of v_characters: every seeded character, whether or not it has accounts yet. */
export interface Character {
  slug: string;
  name: string;
  status: 'designing' | 'live' | 'paused' | string;
  bodies: string[];
  setup: CharacterSetup;
  accounts: CharacterAccount[];
}

/** `runs.details.scan`: what the daily scan did (written by `studio run log --details-file`). */
export interface ScanDetails {
  queries?: string[];
  outliers?: number;
  picks_added?: number;
  auto_approved?: number;
  held?: number;
  skipped?: number;
  vidiq_credits?: number;
}

/** One line of the scheduled-run log (studio.runs). */
export interface RunRow {
  id: string;
  kind: 'daily' | 'weekly' | 'publish' | 'metrics' | string;
  started_at: string;
  finished_at: string | null;
  status: 'ok' | 'budget_stop' | 'error' | string;
  summary: string | null;
  details: { scan?: ScanDetails; vidiq_credits?: number; [k: string]: unknown } | null;
}

/** One row of v_views_daily (migration 0015): what one character's posts gained on one London day, from the metric snapshots. A
 * day nobody measured has no row; a recount can make a day negative (readers clamp it at 0 for display). */
export interface ViewsDay {
  character_slug: string;
  /** The London day, YYYY-MM-DD. */
  day: string;
  views: number;
  follows: number;
}

/** Where a hit is (studio.hits.status, migration 0016): new until the owner uses it ("Use this clip": dropped) or says "Not for
 * us" (dismissed); the hits job marks the ones it files itself dropped too. */
export type HitStatus = 'new' | 'dropped' | 'dismissed';

/**
 * One row of v_hits (migration 0016, terminal v3 spec section 10): a TikTok or Instagram post the daily cloud hits job kept
 * (metadata only, never downloaded), new and posted in the last 14 days (or with no known date), best first. A number the
 * platform did not give is null, never 0. `character_slug` is the character it was searched for; null = the general lane (hot,
 * whatever its topic: any character may take it).
 */
export interface Hit {
  hit_id: string;
  platform: 'tiktok' | 'instagram';
  /** The canonical post link (unique): a TikTok video or an Instagram Reel. */
  url: string;
  creator_handle: string | null;
  followers: number | null;
  views: number | null;
  likes: number | null;
  comments: number | null;
  shares: number | null;
  saves: number | null;
  posted_at: string | null;
  /** At most 300 characters. */
  caption: string | null;
  sound: string | null;
  duration_s: number | null;
  /** A platform CDN link, stored, never fetched by us (it may have expired: the card shows a placeholder then). */
  thumbnail_url: string | null;
  /** What it was found for; null for a trending feed. */
  keyword: string | null;
  character_slug: string | null;
  character_name: string | null;
  /** views ÷ the creator's followers; null without both. */
  reach: number | null;
  /** 0-100 from views, reach and freshness (studio.hits.hit_score): how hot it is. */
  score: number;
  first_seen: string;
  last_seen: string;
  /** Not a column of v_hits (it lists new hits only): absent = new. The demo and the helpers may carry it. */
  status?: HitStatus;
}

/** One character's posting days and slot in `studio.settings.cadence` (`studio plan cadence`): days like "tue", the slot "19:00". */
export interface CadenceEntry {
  days?: string[] | string | null;
  slot?: string | null;
}

export interface Snapshot {
  channels: Channel[];
  queue: QueueClip[];
  library: LibraryClip[];
  budget: Budget | null;
  health: HealthRow[];
  picks: Pick[];
  history: PickHistory[];
  characters: Character[];
  runs: RunRow[];
  /** "In the works": approved picks until they are posted (v_tracker, migration 0010). */
  tracker: TrackerRow[];
  /** Views and follows per character and London day (v_views_daily, migration 0015); empty before it or before any measurement. */
  viewsDaily: ViewsDay[];
  /** The posting days and slot per character (`studio.settings.cadence`); empty when none is set. */
  cadence: Record<string, CadenceEntry>;
  /** The new hits of the last 14 days, best first (v_hits, migration 0016); empty before it or before the first pull. */
  hits: Hit[];
  loadedAt: number;
}

/** What changed since the last load: the board flips these. */
export type ChangeKind = 'clips' | 'posts' | 'favorites' | 'settings' | 'accounts' | 'characters' | 'runs';

/** What the "Make it" sheet adds to an approval (migration 0007 decide_pick); every field is optional. */
export interface DecideExtras {
  /** Approve for this other character too: one sibling pick, one clip each ("Both"). */
  alsoCharacter?: string | null;
  ownerNote?: string | null;
  ownerMode?: OwnerMode | null;
  /** Only sent with ownerMode 'dropin'. */
  ownerPresence?: OwnerPresence | null;
  /** "Gadgets & jewellery": at most 3 items of 1-40 characters. */
  ownerProps?: string[] | null;
  /** in_app | original | ai_beat; the database keeps it only when the mode is not Recreate. */
  ownerMusic?: OwnerMusic | null;
}

/** What the upload needs of a File (a plain object in tests). */
export interface ClipFile {
  name: string;
  size: number;
  type: string;
  /** The browser File itself, for the upload body; absent in tests and the demo. */
  blob?: Blob;
}

export interface Backend {
  readonly kind: 'live' | 'demo';
  load(): Promise<Snapshot>;
  approveClip(id: string, edits?: { caption?: string | null; hook?: string | null; scheduleAt?: string | null }): Promise<void>;
  rejectClip(id: string, reason: string): Promise<void>;
  regenerateClip(id: string, note: string | null): Promise<void>;
  setBudget(cap: number | null, kill: boolean | null): Promise<void>;
  setAccountMode(accountId: string, mode: 'approval' | 'auto', dropinShare?: number | null): Promise<void>;
  decidePick(
    id: string,
    decision: 'approve' | 'skip',
    reason: string | null,
    characterSlug: string | null,
    extras?: DecideExtras,
  ): Promise<void>;
  addOwnerLink(url: string, characterSlug: string, note: string | null): Promise<{ duplicate: boolean }>;
  /**
   * "Attach clip" on the Make-it sheet: uploads the owner's own video for a Drop-in to our `sources` bucket at
   * owner/<pick id>/<timestamp>.<ext> (with progress, 0-100) and records the path with the attach_clip RPC.
   * Returns the storage path. We never download from TikTok or Instagram: this file comes from the owner.
   */
  attachClip(pickId: string, file: ClipFile, onProgress?: (pct: number) => void): Promise<string>;
  /**
   * "Drop a video" (add_drop, migrations 0012 and 0013): a file drop (link null, then attachClip + requestJob process) or a pasted
   * link. `characterSlug` null = "Recommend": the studio chooses after the check.
   */
  addDrop(characterSlug: string | null, link: string | null): Promise<{ pickId: string; duplicate: boolean }>;
  /** The drops table's character menu (set_drop_character, migration 0013): his choice, then the free check again in that voice. */
  setDropCharacter(pickId: string, characterSlug: string): Promise<{ dispatched: boolean }>;
  /** The owner's button (request_job): Checking (process) or Make it (make, with the Adjust). `dispatched` = the cloud job started now. */
  requestJob(pickId: string, kind: 'process' | 'make', adjust?: DropAdjust | null): Promise<{ dispatched: boolean }>;
  /**
   * "Use for another character" (copy_drop, migration 0015): files a version of a checked drop for `characterSlug` (asked from the
   * root or any version: it always points at the root) and starts its free check. Refused with one plain line, nothing written.
   */
  copyDrop(pickId: string, characterSlug: string): Promise<{ pickId: string; dispatched: boolean }>;
  /** The drop card's toggle (set_drop_footage, migration 0012): own footage (true) or a downloaded clip (false). */
  setDropFootage(pickId: string, ownFootage: boolean): Promise<void>;
  /** A hit's buttons (set_hit_status, migration 0016): "Use this clip" marks it dropped (after addDrop of its link), "Not for us"
   * dismissed; `new` puts it back. Refused with one plain line. */
  setHitStatus(hitId: string, status: HitStatus): Promise<void>;
  /** The clip card's Keep (set_drop_keep, migration 0016): retention never deletes a kept clip. */
  setDropKeep(pickId: string, keep: boolean): Promise<void>;
  /** A signed URL of a drop's preview strip in the sources bucket (owner/<pick id>/preview.jpg), or null. */
  previewUrl(path: string): Promise<string | null>;
  signedUrl(path: string): Promise<string | null>;
  /** Live updates; returns an unsubscribe. `onStatus` reports whether the live channel is up. */
  subscribe(onChange: (kind: ChangeKind) => void, onStatus: (up: boolean) => void): () => void;
}
