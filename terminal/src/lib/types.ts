// Row shapes of the studio views (supabase/migrations/0004_terminal_rpc.sql). Numbers that Postgres
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
}

export interface Snapshot {
  channels: Channel[];
  queue: QueueClip[];
  library: LibraryClip[];
  budget: Budget | null;
  health: HealthRow[];
  picks: Pick[];
  history: PickHistory[];
  loadedAt: number;
}

/** What changed since the last load: the board flips these. */
export type ChangeKind = 'clips' | 'posts' | 'favorites' | 'settings' | 'accounts';

export interface Backend {
  readonly kind: 'live' | 'demo';
  load(): Promise<Snapshot>;
  approveClip(id: string, edits?: { caption?: string | null; hook?: string | null; scheduleAt?: string | null }): Promise<void>;
  rejectClip(id: string, reason: string): Promise<void>;
  regenerateClip(id: string, note: string | null): Promise<void>;
  setBudget(cap: number | null, kill: boolean | null): Promise<void>;
  setAccountMode(accountId: string, mode: 'approval' | 'auto', dropinShare?: number | null): Promise<void>;
  decidePick(id: string, decision: 'approve' | 'skip', reason: string | null, characterSlug: string | null): Promise<void>;
  addOwnerLink(url: string, characterSlug: string, note: string | null): Promise<{ duplicate: boolean }>;
  signedUrl(path: string): Promise<string | null>;
  /** Live updates; returns an unsubscribe. `onStatus` reports whether the live channel is up. */
  subscribe(onChange: (kind: ChangeKind) => void, onStatus: (up: boolean) => void): () => void;
}
