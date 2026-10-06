// The live backend: supabase-js with the publishable (anon) key, magic-link auth, RLS does the rest.
// Reads go to the studio views (and the run log, studio.runs), writes only through the studio RPCs of migrations 0004-0008 and
// 0012 (add_drop, request_job: "Drop a video").
// v_tracker (migration 0010) feeds "In the works"; a database without it yet shows that tab empty instead of failing the load.
// The one other write is the owner's own clip for a Drop-in: an upload into bucket `sources` under owner/ (policy of 0008).
import { createClient, type SupabaseClient } from '@supabase/supabase-js';
import { orderRoster } from './roster';
import { checkClipBasics, ownerClipPath } from './rules';
import type { Backend, ChangeKind, ClipFile, DecideExtras, DropAdjust, Snapshot } from './types';

const URL_ = import.meta.env.VITE_SUPABASE_URL as string | undefined;
const KEY = import.meta.env.VITE_SUPABASE_ANON_KEY as string | undefined;

export const hasLiveConfig = Boolean(URL_ && KEY);

// eslint-disable-next-line @typescript-eslint/no-explicit-any
type Client = SupabaseClient<any, 'studio', 'studio'>;
let client: Client | null = null;
export function supabase(): Client {
  if (!hasLiveConfig) throw new Error('VITE_SUPABASE_URL / VITE_SUPABASE_ANON_KEY are not set');
  client ??= createClient(URL_!, KEY!, {
    db: { schema: 'studio' },
    auth: { persistSession: true, autoRefreshToken: true, detectSessionInUrl: true, flowType: 'pkce' },
  }) as Client;
  return client;
}

/** A PostgREST / RPC error as one owner-facing sentence; the SQL raises human sentences already. */
export class StudioError extends Error {
  constructor(message: string, readonly code?: string) {
    super(message);
  }
}

/** PostgREST says this when schema `studio` is not in Settings -> API -> Exposed schemas yet. */
export const isSchemaNotExposed = (e: unknown) =>
  e instanceof StudioError && (e.code === 'PGRST106' || /schema must be one of/i.test(e.message));

function fail(error: { message: string; code?: string } | null): void {
  if (error) throw new StudioError(error.message, error.code);
}

/** An expired sign-in (PostgREST PGRST301/PGRST303, "JWT expired"): a phone that slept past the token's life. */
export const isJwtExpired = (e: unknown) => {
  const x = e as { code?: string; message?: string } | null | undefined;
  return Boolean(x && (x.code === 'PGRST301' || x.code === 'PGRST303' || /jwt expired/i.test(x.message ?? '')));
};

/** PostgREST's "no such table or view" (PGRST205; 42P01 from Postgres itself): a migration not applied yet. */
export const isMissingRelation = (e: { code?: string; message?: string } | null | undefined) =>
  Boolean(e && (e.code === 'PGRST205' || e.code === '42P01' || /could not find the table/i.test(e.message ?? '')));

// numeric / bigint columns can arrive as strings; everything numeric goes through here.
const n = (v: unknown): number | null => (v == null || v === '' ? null : Number(v));

function normalise<T extends Record<string, unknown>>(row: T, keys: string[]): T {
  const out: Record<string, unknown> = { ...row };
  for (const k of keys) if (k in out) out[k] = n(out[k]);
  return out as T;
}

/** An upload with progress (fetch has none): XMLHttpRequest PUT-style POST to Supabase Storage, 0-100 to `onProgress`. */
function putWithProgress(url: string, body: Blob, headers: Record<string, string>, onProgress?: (pct: number) => void): Promise<void> {
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.open('POST', url);
    for (const [k, v] of Object.entries(headers)) xhr.setRequestHeader(k, v);
    xhr.upload.onprogress = (e) => {
      if (e.lengthComputable) onProgress?.(Math.min(99, Math.round((e.loaded / e.total) * 100)));
    };
    xhr.onerror = () => reject(new StudioError('The upload failed: check the connection and try again'));
    xhr.onabort = () => reject(new StudioError('The upload was cancelled'));
    xhr.onload = () => {
      if (xhr.status >= 200 && xhr.status < 300) {
        onProgress?.(100);
        resolve();
        return;
      }
      let message = `The upload was refused (${xhr.status})`;
      try {
        const body = JSON.parse(xhr.responseText) as { message?: string; error?: string };
        message = body.message ?? body.error ?? message;
      } catch {
        /* keep the status line */
      }
      reject(new StudioError(message));
    };
    xhr.send(body);
  });
}

export class LiveBackend implements Backend {
  readonly kind = 'live' as const;
  private sb = supabase();

  /** The snapshot; an expired sign-in is renewed once and the load retried, so a phone back from sleep just loads. */
  async load(): Promise<Snapshot> {
    await this.sb.auth.getSession(); // renews a token that ran out while the app slept
    try {
      return await this.loadOnce();
    } catch (e) {
      if (!isJwtExpired(e)) throw e;
      const { error } = await this.sb.auth.refreshSession();
      if (error) throw new StudioError('Your sign-in ran out: sign in again with the email link', error.code);
      return this.loadOnce();
    }
  }

  private async loadOnce(): Promise<Snapshot> {
    const sb = this.sb;
    const [channels, queue, library, budget, health, picks, history, characters, runs, tracker] = await Promise.all([
      sb.from('v_channels').select('*'),
      sb.from('v_queue').select('*').order('created_at'),
      sb.from('v_library').select('*').order('created_at', { ascending: false }).limit(300),
      sb.from('v_budget').select('*').maybeSingle(),
      sb.from('v_health').select('*'),
      sb.from('v_picks').select('*').order('total_score', { ascending: false, nullsFirst: false }).order('created_at'),
      sb.from('v_pick_history').select('*').order('created_at', { ascending: false }).limit(100),
      sb.from('v_characters').select('*').order('slug'),
      // the Scanner card: the daily run's rows (RLS: the owner's), newest first; a month of them is plenty
      sb.from('runs').select('id,kind,started_at,finished_at,status,summary,details').eq('kind', 'daily').order('started_at', { ascending: false }).limit(60),
      sb.from('v_tracker').select('*'),
    ]);
    for (const r of [channels, queue, library, budget, health, picks, history, characters, runs]) fail(r.error);
    if (!isMissingRelation(tracker.error)) fail(tracker.error);
    const num = [
      'views', 'outlier_x', 'total_score', 'virality', 'reach', 'freshness', 'fit', 'feasibility', 'saturation', 'velocity', 'saturation_count',
      'recognisability', 'original_views', 'est_credits',
    ];
    return {
      channels: (channels.data ?? []).map((r) =>
        normalise(r, ['dropin_share', 'dropin_ratio', 'views_7d', 'follows', 'median_outlier_x', 'hit_rate', 'approved_posts']),
      ),
      queue: (queue.data ?? []).map((r) => normalise(r, ['cost_credits'])),
      library: (library.data ?? []).map((r) => normalise(r, ['cost_credits', 'outlier_x', 'views'])),
      budget: budget.data ? normalise(budget.data, ['cap', 'settled', 'reserved', 'committed', 'projected']) : null,
      health: health.data ?? [],
      picks: (picks.data ?? []).map((r) => normalise(r, num)),
      history: (history.data ?? []).map((r) => normalise(r, num)),
      // the owner's order (Franz, Reginald, Lenny, then any other, a paused one last), not the view's alphabetical one
      characters: orderRoster((characters.data ?? []).map((r) => ({ ...r, setup: r.setup ?? {}, accounts: r.accounts ?? [] }))),
      runs: runs.data ?? [],
      tracker: (tracker.error ? [] : tracker.data ?? []).map((r) =>
        normalise(r, ['views', 'outlier_x', 'velocity', 'credits_spent', 'latest_views']),
      ),
      loadedAt: Date.now(),
    } as Snapshot;
  }

  private async rpc(fn: string, args: Record<string, unknown>) {
    const { data, error } = await this.sb.rpc(fn, args);
    fail(error);
    return data as Record<string, unknown> | null;
  }

  async approveClip(id: string, edits: { caption?: string | null; hook?: string | null; scheduleAt?: string | null } = {}) {
    await this.rpc('approve_clip', {
      clip_id: id, caption: edits.caption ?? null, hook: edits.hook ?? null, schedule_at: edits.scheduleAt ?? null,
    });
  }
  async rejectClip(id: string, reason: string) {
    await this.rpc('reject_clip', { clip_id: id, reason });
  }
  async regenerateClip(id: string, note: string | null) {
    await this.rpc('regenerate_clip', { clip_id: id, note });
  }
  async setBudget(cap: number | null, kill: boolean | null) {
    await this.rpc('set_budget', { cap, kill });
  }
  async setAccountMode(accountId: string, mode: 'approval' | 'auto', dropinShare: number | null = null) {
    await this.rpc('set_account_mode', { account_id: accountId, mode, dropin_share: dropinShare });
  }
  async decidePick(
    id: string, decision: 'approve' | 'skip', reason: string | null, characterSlug: string | null, extras: DecideExtras = {},
  ) {
    await this.rpc('decide_pick', {
      pick_id: id, decision, reason, character_slug: characterSlug,
      // only what the owner set: a plain Approve or Skip sends exactly what it always did
      ...(extras.alsoCharacter ? { also_character: extras.alsoCharacter } : {}),
      ...(extras.ownerNote ? { owner_note: extras.ownerNote } : {}),
      ...(extras.ownerMode ? { owner_mode: extras.ownerMode } : {}),
      ...(extras.ownerPresence ? { owner_presence: extras.ownerPresence } : {}),
      ...(extras.ownerProps?.length ? { owner_props: extras.ownerProps } : {}),
      ...(extras.ownerMusic ? { owner_music: extras.ownerMusic } : {}),
    });
  }
  async addOwnerLink(url: string, characterSlug: string, note: string | null) {
    const r = await this.rpc('add_owner_link', { url, character_slug: characterSlug, note });
    return { duplicate: Boolean(r?.duplicate) };
  }
  async attachClip(pickId: string, file: ClipFile, onProgress?: (pct: number) => void) {
    if (!file.blob) throw new Error('There is no file to upload');
    const checked = checkClipBasics(file); // the duration was checked where the file was chosen
    if (!checked.ok) throw new Error(checked.reason);
    const path = ownerClipPath(pickId, file, Date.now());
    const { data } = await this.sb.auth.getSession();
    if (!data.session) throw new Error('Sign in again to upload the clip');
    await putWithProgress(`${URL_}/storage/v1/object/sources/${path}`, file.blob, {
      Authorization: `Bearer ${data.session.access_token}`,
      apikey: KEY!,
      'Content-Type': file.type || 'video/mp4',
      'x-upsert': 'false',
    }, onProgress);
    await this.rpc('attach_clip', { pick_id: pickId, storage_path: path });
    return path;
  }
  async addDrop(characterSlug: string, link: string | null) {
    const r = await this.rpc('add_drop', { character_slug: characterSlug, link });
    if (!r || typeof r.id !== 'string') throw new StudioError('The drop was not filed: try again');
    return { pickId: r.id, duplicate: Boolean(r.duplicate) };
  }
  async requestJob(pickId: string, kind: 'process' | 'make', adjust: DropAdjust | null = null) {
    const r = await this.rpc('request_job', {
      pick_id: pickId, kind, ...(adjust && Object.keys(adjust).length ? { adjust } : {}),
    });
    return { dispatched: Boolean(r?.dispatched) };
  }
  async setDropFootage(pickId: string, ownFootage: boolean) {
    await this.rpc('set_drop_footage', { pick_id: pickId, own_footage: ownFootage });
  }
  async previewUrl(path: string) {
    // a drop's preview strip lives under sources/owner/<pick id>/ (the owner may read there: storage policy of 0008)
    if (!/^owner\/[0-9a-f-]{36}\/[^/\s]+$/i.test(path)) return null;
    const { data, error } = await this.sb.storage.from('sources').createSignedUrl(path, 3600);
    if (error) return null;
    return data.signedUrl;
  }
  async signedUrl(path: string) {
    const { data, error } = await this.sb.storage.from('clips').createSignedUrl(path, 3600);
    if (error) return null;
    return data.signedUrl;
  }

  subscribe(onChange: (kind: ChangeKind) => void, onStatus: (up: boolean) => void) {
    const channel = this.sb.channel('studio-terminal');
    for (const table of ['clips', 'posts', 'favorites', 'characters', 'accounts', 'runs'] as const) {
      channel.on('postgres_changes', { event: '*', schema: 'studio', table }, () => onChange(table));
    }
    channel.subscribe((status) => onStatus(status === 'SUBSCRIBED'));
    return () => {
      void this.sb.removeChannel(channel);
    };
  }
}
