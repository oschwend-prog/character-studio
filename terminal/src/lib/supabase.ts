// The live backend: supabase-js with the publishable (anon) key, magic-link auth, RLS does the rest.
// Reads go to the studio views (and the run log, studio.runs), writes only through the studio RPCs of migrations 0004-0007.
import { createClient, type SupabaseClient } from '@supabase/supabase-js';
import type { Backend, ChangeKind, DecideExtras, Snapshot } from './types';

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

// numeric / bigint columns can arrive as strings; everything numeric goes through here.
const n = (v: unknown): number | null => (v == null || v === '' ? null : Number(v));

function normalise<T extends Record<string, unknown>>(row: T, keys: string[]): T {
  const out: Record<string, unknown> = { ...row };
  for (const k of keys) if (k in out) out[k] = n(out[k]);
  return out as T;
}

export class LiveBackend implements Backend {
  readonly kind = 'live' as const;
  private sb = supabase();

  async load(): Promise<Snapshot> {
    const sb = this.sb;
    const [channels, queue, library, budget, health, picks, history, characters, runs] = await Promise.all([
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
    ]);
    for (const r of [channels, queue, library, budget, health, picks, history, characters, runs]) fail(r.error);
    const num = ['views', 'outlier_x', 'total_score', 'virality', 'reach', 'freshness', 'fit', 'feasibility', 'saturation'];
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
      characters: (characters.data ?? []).map((r) => ({ ...r, setup: r.setup ?? {}, accounts: r.accounts ?? [] })),
      runs: runs.data ?? [],
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
    });
  }
  async addOwnerLink(url: string, characterSlug: string, note: string | null) {
    const r = await this.rpc('add_owner_link', { url, character_slug: characterSlug, note });
    return { duplicate: Boolean(r?.duplicate) };
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
