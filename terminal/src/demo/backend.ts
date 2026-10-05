// Demo mode (?demo=1 or VITE_DEMO=1): the whole terminal on an in-memory studio, so the UI can be
// shown and verified without a live connection. The Viral Picks are the real batch-1 picks
// (docs/launch/viral-picks-2026-10-04.md, parsed by studio.seed); every clip, post, metric and credit
// figure is SYNTHETIC and the UI says so. Actions follow the same rules as the SQL RPCs.
import picksJson from './batch1-picks.json';
import { canonicalVideoUrl, AUTOPILOT_MIN_APPROVED } from '../lib/rules';
import { londonDayKey, londonWallToIso } from '../lib/format';
import type {
  Backend, Budget, Channel, ChangeKind, ClipState, HealthRow, LibraryClip, Pick, PickHistory, Platform, PostStatus,
  QueueClip, Snapshot,
} from '../lib/types';

interface Account { id: string; character_slug: string; platform: Platform; handle: string; connected: boolean; mode: 'approval' | 'auto'; dropin_share: number }
interface Clip {
  id: string; character_slug: string; mode: 'dropin' | 'recreate'; state: ClipState; hook: string | null; caption: string | null;
  hashtags: string[]; master_path: string | null; cost: number | null; outlier_x: number | null; created_at: string;
  reject_reason: string | null; qa: QueueClip['qa']; features: Record<string, unknown>; source: { kind: string; url: string | null; credit: string | null; trend: string | null } | null;
}
interface Post { id: string; clip_id: string; account_id: string; scheduled_for: string; status: PostStatus; url: string | null; error: string | null; views: number | null; likes: number | null; comments: number | null; shares: number | null; saves: number | null; follows: number | null }
interface Fav {
  id: string; url: string; platform: string; creator_handle: string | null; views: number | null; outlier_x: number | null;
  origin: 'scan' | 'owner'; character_slug: string | null; proposal: Record<string, unknown>; scores: Record<string, number>;
  total_score: number | null; note: string | null; status: string; created_at: string; clip_id: string | null;
}

const NAMES: Record<string, string> = { biscuit: 'Biscuit', reginald: 'Reginald' };
const SLOTS: Record<string, string> = { biscuit: '19:00', reginald: '19:30' };
const CADENCE = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri']; // weeks 3+ cadence
const DAY = 86_400_000;

let seq = 0;
const uid = (tag: string) => {
  seq += 1;
  const hex = (seq * 2654435761 + tag.length * 97).toString(16).padStart(8, '0').slice(-8);
  return `${hex}-${tag.padEnd(4, '0').slice(0, 4).replace(/[^0-9a-f]/gi, 'a')}-4000-8000-${String(seq).padStart(12, '0')}`;
};

/** London slot `hh:mm` on the London day `offset` days from `now`. */
function slotOn(slug: string, now: number, offset: number): string {
  const day = londonDayKey(now + offset * DAY);
  return londonWallToIso(`${day}T${SLOTS[slug]}`);
}

function upcomingSlot(slug: string, now: number): string {
  for (let i = 0; i < 8; i++) {
    const iso = slotOn(slug, now, i);
    const wd = new Intl.DateTimeFormat('en-GB', { timeZone: 'Europe/London', weekday: 'short' }).format(new Date(iso));
    if (CADENCE.includes(wd) && Date.parse(iso) > now) return iso;
  }
  return slotOn(slug, now, 1);
}

class DemoError extends Error {}

export class DemoBackend implements Backend {
  readonly kind = 'demo' as const;
  private accounts: Account[] = [];
  private clips: Clip[] = [];
  private posts: Post[] = [];
  private favs: Fav[] = [];
  private cap = 6000;
  private kill = false;
  private settled: Record<string, number> = {}; // clip id -> credits settled this month
  private listeners = new Set<(k: ChangeKind) => void>();

  constructor(private readonly now: () => number = Date.now) {
    this.seed();
  }

  // ---- fixture ------------------------------------------------------------------------------------

  private seed() {
    const now = this.now();
    const acc = (character_slug: string, platform: Platform, handle: string, mode: Account['mode'], share: number) => {
      const a = { id: uid(`a${character_slug[0]}${platform[0]}`), character_slug, platform, handle, connected: true, mode, dropin_share: share };
      this.accounts.push(a);
      return a;
    };
    const btt = acc('biscuit', 'tiktok', '@biscuit.moves', 'approval', 0.7);
    const big = acc('biscuit', 'instagram', 'biscuit.moves', 'auto', 0.4);
    const rtt = acc('reginald', 'tiktok', '@reginald.thebutler', 'approval', 0.7);
    const rig = acc('reginald', 'instagram', 'reginald.thebutler', 'approval', 0.4);

    const clip = (slug: string, hook: string, mode: Clip['mode'], state: ClipState, daysAgo: number, extra: Partial<Clip> = {}): Clip => {
      const c: Clip = {
        id: uid(`c${slug[0]}`), character_slug: slug, mode, state, hook, caption: null, hashtags: [],
        master_path: `${slug}/demo-${seq}.mp4`, cost: 160, outlier_x: null,
        created_at: new Date(now - daysAgo * DAY - 9 * 3600_000).toISOString(), reject_reason: null,
        qa: { tech: 'ok', problems: [], visual: 'eyes right (blue viewer-left), outfit ok' },
        features: { format_id: slug === 'biscuit' ? 'B-DANCE' : 'R-DEADPAN', hook_text: hook }, source: null, ...extra,
      };
      this.clips.push(c);
      return c;
    };
    const post = (c: Clip, a: Account, daysAgo: number, status: PostStatus, views: number | null, extra: Partial<Post> = {}) => {
      const at = slotOn(c.character_slug, now, -daysAgo);
      const p: Post = {
        id: uid('p'), clip_id: c.id, account_id: a.id, scheduled_for: at, status,
        url: status === 'posted' ? (a.platform === 'tiktok' ? `https://www.tiktok.com/${a.handle}` : `https://www.instagram.com/${a.handle}/`) : null,
        error: null, views, likes: views && Math.round(views * 0.081), comments: views && Math.round(views * 0.004),
        shares: views && Math.round(views * 0.012), saves: views && Math.round(views * 0.006), follows: views && Math.round(views * 0.0035),
        ...extra,
      };
      this.posts.push(p);
      return p;
    };

    // Biscuit: seven posted clips (both channels), so posting autopilot is unlocked on both.
    const bHistory: [string, Clip['mode'], number, number | null, number, number][] = [
      ["my eyes don't match. my moves do.", 'recreate', 13, 4.2, 48_200, 21_400],
      ['lead dancer. obviously.', 'recreate', 12, 1.1, 12_900, 6_100],
      ['he hits every single beat', 'dropin', 11, 3.6, 41_800, 9_800],
      ['me at the vet acting fine', 'recreate', 6, 0.8, 9_400, 4_700],
      ['two of me is illegal', 'recreate', 5, 2.1, 25_300, 11_900],
      ["forgot I'm a dog for a sec", 'recreate', 4, 1.6, 19_100, 8_800],
      ['going as myself this year', 'recreate', 1, null, 3_900, 1_700],
    ];
    for (const [hook, mode, ago, x, vt, vi] of bHistory) {
      const c = clip('biscuit', hook, mode, 'posted', ago, { outlier_x: x, cost: mode === 'dropin' ? 118 : 158 });
      post(c, btt, ago, 'posted', vt);
      post(c, big, ago, 'posted', vi);
      if (ago <= 1) this.settled[c.id] = c.cost ?? 0;
    }
    // Reginald: four clips, so autopilot is still locked (4 of 6).
    const rHistory: [string, number, number | null, number, number][] = [
      ['keep your eyes on the quiff', 6, 1.9, 22_600, 13_100],
      ['reasons to hire a butler:', 5, 0.6, 7_200, 3_900],
      ['watch the tea, not him', 4, 3.3, 61_500, 27_200],
    ];
    for (const [hook, ago, x, vt, vi] of rHistory) {
      const c = clip('reginald', hook, 'recreate', 'posted', ago, { outlier_x: x, cost: 162 });
      post(c, rtt, ago, 'posted', vt);
      post(c, rig, ago, 'posted', vi);
    }
    const fine = clip('reginald', 'everything is fine, sir', 'recreate', 'scheduled', 1, { cost: 160 });
    post(fine, rtt, 1, 'posted', 5_800);
    post(fine, rig, 1, 'needs_check', null, {
      error: 'Postiz timed out after the upload: check whether the reel is live before retrying',
    });
    this.settled[fine.id] = 160;

    // Today: Biscuit's eye loop is booked for 19:00 on both channels.
    const eyeLoop = clip('biscuit', "eyes don't match. moves do.", 'recreate', 'scheduled', 0, {
      cost: 84, caption: 'blue one sees the beat. amber one sees you. 🌭', features: { format_id: 'B-EYELOOP', hook_text: "eyes don't match. moves do.", seamless_loop: true },
    });
    for (const a of [btt, big]) {
      this.posts.push({
        id: uid('p'), clip_id: eyeLoop.id, account_id: a.id, scheduled_for: slotOn('biscuit', now, 0), status: 'scheduled',
        url: null, error: null, views: null, likes: null, comments: null, shares: null, saves: null, follows: null,
      });
    }
    this.settled[eyeLoop.id] = 84;

    // The queue: three finished clips from approved Viral Picks.
    const raw = picksJson as unknown as Array<Fav & { ref: string; rank: number }>;
    const pickByRef = new Map<string, Fav>();
    raw.forEach((p, i) => {
      const f: Fav = {
        id: uid(`f${p.ref.toLowerCase()}`), url: p.url, platform: p.platform, creator_handle: p.creator_handle, views: p.views,
        outlier_x: p.outlier_x, origin: 'scan', character_slug: p.character_slug, proposal: p.proposal, scores: p.scores,
        total_score: p.total_score, note: null, status: p.status,
        created_at: new Date(now - 30 * 3600_000 + i * 60_000).toISOString(), clip_id: null,
      };
      this.favs.push(f);
      pickByRef.set(p.ref, f);
    });
    const queued: [string, string, string, number, string][] = [
      ['B1', 'reginald', 'first day as head butler', 162, 'first day on the job. nobody saw the tray move. #butler #deadpan'],
      ['B2', 'reginald', 'POV: you rang for tea', 158, 'the bell can wait. the song cannot. #teatime #butler'],
      ['D6', 'biscuit', 'official taste inspector', 171, 'croissant: approved. crumbs: also approved. #dachshund #sausagedog'],
    ];
    queued.forEach(([ref, slug, hook, cost, caption], i) => {
      const f = pickByRef.get(ref)!;
      const c = clip(slug, hook, 'recreate', 'awaiting_approval', 0, {
        cost, caption, hashtags: caption.match(/#\w+/g) ?? [],
        created_at: new Date(now - (3 - i) * 3600_000).toISOString(),
        features: { format_id: slug === 'biscuit' ? 'B-EGO' : 'R-DEADPAN', hook_text: hook, fav_id: f.id },
        source: { kind: 'synthetic', url: null, credit: f.creator_handle, trend: String(f.proposal.concept ?? '').slice(0, 60) || null },
        qa: { tech: 'ok', problems: [], visual: slug === 'reginald' ? 'quiff rigid, no smile, eyes right' : 'eyes right, crumbs on onesie, paws clean' },
      });
      f.status = 'made';
      f.clip_id = c.id;
      this.settled[c.id] = cost;
    });
    const d4 = pickByRef.get('D4');
    if (d4) { d4.status = 'made'; d4.clip_id = eyeLoop.id; }
    const d5 = pickByRef.get('D5');
    if (d5) d5.status = 'analysed';
  }

  // ---- helpers mirroring the SQL ------------------------------------------------------------------

  private emit(kind: ChangeKind) {
    for (const l of this.listeners) l(kind);
  }

  private connectedFor(slug: string) {
    return this.accounts.filter((a) => a.character_slug === slug && a.connected);
  }

  private dropinRatio(accountId: string, exclude?: string) {
    const recent = this.posts
      .filter((p) => p.account_id === accountId && p.clip_id !== exclude)
      .sort((a, b) => Date.parse(a.scheduled_for) - Date.parse(b.scheduled_for) || a.id.localeCompare(b.id))
      .slice(-10);
    if (!recent.length) return 0;
    return recent.filter((p) => this.clips.find((c) => c.id === p.clip_id)?.mode === 'dropin').length / recent.length;
  }

  private targetsFor(c: Clip) {
    const connected = this.connectedFor(c.character_slug);
    return c.mode === 'recreate' ? connected : connected.filter((a) => this.dropinRatio(a.id, c.id) < a.dropin_share);
  }

  /** queue_block_reason (migration 0005). */
  private blockReason(c: Clip): string | null {
    if (!c.master_path) return 'no master file yet';
    if (!this.connectedFor(c.character_slug).length) return `no connected account for ${c.character_slug}`;
    if (!this.targetsFor(c).length) return `no account of ${c.character_slug} may take this ${c.mode} clip`;
    return null;
  }

  private approvedPosts(accountId: string) {
    return this.posts.filter((p) => p.account_id === accountId).length;
  }

  private clip(id: string) {
    const c = this.clips.find((x) => x.id === id);
    if (!c) throw new DemoError(`unknown clip ${id}`);
    return c;
  }

  // ---- Backend ------------------------------------------------------------------------------------

  async load(): Promise<Snapshot> {
    const now = this.now();
    const today = londonDayKey(now);
    const acct = new Map(this.accounts.map((a) => [a.id, a]));

    const channels: Channel[] = this.accounts.map((a) => {
      const mine = this.posts.filter((p) => p.account_id === a.id);
      const posted = mine.filter((p) => p.status === 'posted');
      const xs = [...new Set(posted.map((p) => p.clip_id))]
        .map((id) => this.clips.find((c) => c.id === id)?.outlier_x)
        .filter((x): x is number => typeof x === 'number')
        .sort((p, q) => p - q);
      const median = xs.length ? (xs.length % 2 ? xs[(xs.length - 1) / 2] : (xs[xs.length / 2 - 1] + xs[xs.length / 2]) / 2) : null;
      const approved = this.approvedPosts(a.id);
      return {
        account_id: a.id, character_slug: a.character_slug, character_name: NAMES[a.character_slug], character_status: 'live',
        platform: a.platform, handle: a.handle, connected: a.connected, mode: a.mode, dropin_share: a.dropin_share,
        dropin_ratio: this.dropinRatio(a.id), approved_posts: approved, autopilot_min_approved: AUTOPILOT_MIN_APPROVED,
        autopilot_unlocked: approved >= AUTOPILOT_MIN_APPROVED,
        posts_posted: posted.length,
        posts_scheduled: mine.filter((p) => p.status === 'scheduled' || p.status === 'posting').length,
        posts_problem: mine.filter((p) => p.status === 'failed' || p.status === 'needs_check').length,
        views_7d: posted.filter((p) => Date.parse(p.scheduled_for) >= now - 7 * DAY).reduce((s, p) => s + (p.views ?? 0), 0),
        follows: posted.reduce((s, p) => s + (p.follows ?? 0), 0),
        median_outlier_x: median,
        hit_rate: xs.length ? xs.filter((x) => x >= 3).length / xs.length : null,
        measured_clips: xs.length,
        bar_status: null,
        next_slot: upcomingSlot(a.character_slug, now),
        today_posts: mine
          .filter((p) => londonDayKey(p.scheduled_for) === today)
          .map((p) => {
            const c = this.clip(p.clip_id);
            return { post_id: p.id, clip_id: p.clip_id, scheduled_for: p.scheduled_for, status: p.status, hook: c.hook, mode: c.mode, url: p.url };
          }),
      };
    });

    const queue: QueueClip[] = this.clips
      .filter((c) => c.state === 'awaiting_approval')
      .sort((a, b) => Date.parse(a.created_at) - Date.parse(b.created_at))
      .map((c) => {
        const fav = this.favs.find((f) => f.clip_id === c.id);
        return {
          id: c.id, character_slug: c.character_slug, character_name: NAMES[c.character_slug], mode: c.mode, state: c.state,
          master_path: c.master_path, hook: c.hook, caption: c.caption, hashtags: c.hashtags, cost_credits: c.cost, qa: c.qa,
          features: c.features, created_at: c.created_at, source_kind: c.source?.kind ?? null, source_url: c.source?.url ?? null,
          source_credit: c.source?.credit ?? null, source_trend: c.source?.trend ?? null,
          targets: this.targetsFor(c).map((a) => ({ account_id: a.id, platform: a.platform, handle: a.handle, mode: a.mode })),
          next_slot: upcomingSlot(c.character_slug, now), pick_id: fav?.id ?? null, pick_url: fav?.url ?? null,
          blocked_reason: this.blockReason(c),
        };
      });

    const library: LibraryClip[] = [...this.clips]
      .sort((a, b) => Date.parse(b.created_at) - Date.parse(a.created_at))
      .map((c) => {
        const ps = this.posts.filter((p) => p.clip_id === c.id);
        const views = ps.reduce<number | null>((s, p) => (p.views == null ? s : (s ?? 0) + p.views), null);
        const posted = ps.filter((p) => p.status === 'posted').map((p) => p.scheduled_for).sort();
        return {
          id: c.id, character_slug: c.character_slug, character_name: NAMES[c.character_slug], mode: c.mode, state: c.state,
          hook: c.hook, caption: c.caption, master_path: c.master_path, reject_reason: c.reject_reason, created_at: c.created_at,
          cost_credits: c.cost, outlier_x: c.outlier_x, format_id: (c.features.format_id as string) ?? null,
          posts: ps.map((p) => {
            const a = acct.get(p.account_id)!;
            return {
              post_id: p.id, platform: a.platform, handle: a.handle, status: p.status, scheduled_for: p.scheduled_for, url: p.url,
              views: p.views, likes: p.likes, comments: p.comments, shares: p.shares, saves: p.saves,
              captured_at: p.views == null ? null : new Date(now - 2 * 3600_000).toISOString(),
            };
          }),
          platforms: [...new Set(ps.map((p) => acct.get(p.account_id)!.platform))].sort(),
          views, posted_at: posted[0] ?? null,
        };
      });

    const bySlug: Record<string, number> = { biscuit: 0, reginald: 0 };
    let settled = 0;
    for (const [id, cr] of Object.entries(this.settled)) {
      settled += cr;
      const c = this.clips.find((x) => x.id === id);
      if (c) bySlug[c.character_slug] += cr;
    }
    const reserved = 0;
    const p = new Intl.DateTimeFormat('en-CA', { timeZone: 'Europe/London', year: 'numeric', month: '2-digit', day: '2-digit' })
      .format(new Date(now)).split('-').map(Number);
    const daysIn = new Date(Date.UTC(p[0], p[1], 0)).getUTCDate();
    const budget: Budget = {
      month: `${p[0]}-${String(p[1]).padStart(2, '0')}`, cap: this.cap, kill_switch: this.kill, settled, reserved,
      committed: settled + reserved, day_of_month: p[2], days_in_month: daysIn,
      projected: Math.round(((settled + reserved) / p[2]) * daysIn),
      by_character: Object.entries(bySlug).map(([slug, cr]) => ({ slug, name: NAMES[slug], settled: cr, reserved: 0, committed: cr })),
    };

    const health: HealthRow[] = this.posts
      .filter((x) => x.status === 'failed' || x.status === 'needs_check')
      .map((x) => ({
        kind: 'post', severity: x.status === 'failed' ? 'critical' : 'warning',
        message: `post on ${acct.get(x.account_id)?.handle} is ${x.status}${x.error ? `: ${x.error}` : ''}`,
        ref_id: x.id, since: x.scheduled_for,
      }));
    if (budget.cap > 0 && budget.committed * 100 >= budget.cap * 80) {
      health.push({
        kind: 'budget', severity: budget.committed >= budget.cap ? 'critical' : 'warning',
        message: `credits committed in ${budget.month}: ${budget.committed} of ${budget.cap}, at or past 80% of the monthly cap`,
        ref_id: null, since: new Date(now).toISOString(),
      });
    }

    const name = (s: string | null) => (s ? NAMES[s] ?? s : null);
    const num = (f: Fav, k: string) => (typeof f.scores[k] === 'number' ? f.scores[k] : null);
    const picks: Pick[] = this.favs
      .filter((f) => f.status === 'new')
      .map((f) => ({
        id: f.id, url: f.url, platform: f.platform, creator_handle: f.creator_handle, views: f.views, outlier_x: f.outlier_x,
        origin: f.origin, character_slug: f.character_slug, character_name: name(f.character_slug),
        intended_character: (f.proposal.intended_character as string) ?? null, total_score: f.total_score,
        virality: num(f, 'virality'), reach: num(f, 'reach'), freshness: num(f, 'freshness'), fit: num(f, 'fit'),
        feasibility: num(f, 'feasibility'), saturation: num(f, 'saturation'),
        proposed_mode: (f.proposal.mode as string) ?? null, hook: (f.proposal.hook as string) ?? null,
        prop: (f.proposal.prop as string) ?? null, concept: (f.proposal.concept as string) ?? null,
        enhancement: (f.proposal.enhancement as string) ?? null, needs: (f.proposal.needs as string) ?? null,
        decision: (f.proposal.decision as Pick['decision']) ?? null, hold_reason: (f.proposal.hold_reason as string) ?? null,
        note: f.note, status: f.status, created_at: f.created_at,
      }));
    const history: PickHistory[] = this.favs
      .filter((f) => f.status !== 'new')
      .sort((a, b) => (b.total_score ?? 0) - (a.total_score ?? 0))
      .map((f) => ({
        id: f.id, url: f.url, platform: f.platform, creator_handle: f.creator_handle, views: f.views, outlier_x: f.outlier_x,
        origin: f.origin, character_slug: f.character_slug, character_name: name(f.character_slug), total_score: f.total_score,
        hook: (f.proposal.hook as string) ?? null, concept: (f.proposal.concept as string) ?? null,
        decision: (f.proposal.decision as PickHistory['decision']) ?? null, note: f.note, status: f.status, created_at: f.created_at,
        clip_id: f.clip_id, clip_state: f.clip_id ? this.clips.find((c) => c.id === f.clip_id)?.state ?? null : null,
      }));

    return { channels, queue, library, budget, health, picks, history, loadedAt: now };
  }

  async approveClip(id: string, edits: { caption?: string | null; hook?: string | null; scheduleAt?: string | null } = {}) {
    const c = this.clip(id);
    if (c.state !== 'awaiting_approval' && c.state !== 'approved') {
      throw new DemoError(`clip ${id} is ${c.state}: only a clip awaiting approval can be approved`);
    }
    const blocked = this.blockReason(c);
    if (blocked) throw new DemoError(`cannot approve clip ${id}: ${blocked}`);
    const targets = this.targetsFor(c);
    const at = edits.scheduleAt ?? upcomingSlot(c.character_slug, this.now());
    if (edits.caption?.trim()) c.caption = edits.caption.trim(); // blank keeps what is there
    if (edits.hook?.trim()) c.hook = edits.hook.trim();
    for (const a of targets) {
      if (!this.posts.some((p) => p.clip_id === c.id && p.account_id === a.id)) {
        this.posts.push({
          id: uid('p'), clip_id: c.id, account_id: a.id, scheduled_for: at, status: 'scheduled', url: null, error: null,
          views: null, likes: null, comments: null, shares: null, saves: null, follows: null,
        });
      }
    }
    c.state = 'scheduled';
    this.emit('clips');
    this.emit('posts');
  }

  async rejectClip(id: string, reason: string) {
    if (!reason.trim()) throw new DemoError('a rejection needs a reason (it feeds QA and the playbook)');
    const c = this.clip(id);
    if (c.state !== 'awaiting_approval') throw new DemoError(`clip ${id} is ${c.state}: only a clip awaiting approval can be rejected`);
    c.state = 'rejected';
    c.reject_reason = reason.trim();
    this.emit('clips');
  }

  async regenerateClip(id: string, note: string | null) {
    const c = this.clip(id);
    if (c.state !== 'awaiting_approval') throw new DemoError(`clip ${id} is ${c.state}: only a clip awaiting approval can be regenerated`);
    c.state = 'rejected';
    c.reject_reason = `regenerate${note?.trim() ? `: ${note.trim()}` : ''}`;
    this.clips.push({
      ...c, id: uid('cr'), state: 'planned', master_path: null, cost: null, reject_reason: null, created_at: new Date(this.now()).toISOString(),
      features: { ...c.features, rerolls: 0, regenerate_of: c.id, ...(note?.trim() ? { regenerate_note: note.trim() } : {}) },
    });
    this.emit('clips');
  }

  async setBudget(cap: number | null, kill: boolean | null) {
    if (cap != null && (cap < 0 || !Number.isInteger(cap))) throw new DemoError('the cap must be a whole number of credits, 0 or more');
    if (cap != null) this.cap = cap;
    if (kill != null) this.kill = kill;
    this.emit('settings');
  }

  async setAccountMode(accountId: string, mode: 'approval' | 'auto', dropinShare: number | null = null) {
    const a = this.accounts.find((x) => x.id === accountId);
    if (!a) throw new DemoError(`unknown account ${accountId}`);
    const approved = this.approvedPosts(a.id);
    if (mode === 'auto' && a.mode !== 'auto' && approved < AUTOPILOT_MIN_APPROVED) {
      throw new DemoError(`autopilot unlocks after 6 approved posts on ${a.handle} (${approved} so far)`);
    }
    if (dropinShare != null && (dropinShare < 0 || dropinShare > 1)) throw new DemoError('dropin share must be between 0 and 1');
    a.mode = mode;
    if (dropinShare != null) a.dropin_share = dropinShare;
    this.emit('accounts');
  }

  async decidePick(id: string, decision: 'approve' | 'skip', reason: string | null, characterSlug: string | null) {
    const f = this.favs.find((x) => x.id === id);
    if (!f) throw new DemoError(`unknown pick ${id}`);
    if (f.status === 'queued' || f.status === 'made') throw new DemoError(`pick ${id} is already ${f.status}: too late to decide`);
    const slug = characterSlug || f.character_slug;
    if (decision === 'approve' && !slug) throw new DemoError('choose a character before approving this pick');
    const { hold_reason: _drop, ...rest } = f.proposal;
    void _drop;
    f.proposal = { ...rest, decision: { decision, by: 'owner', reason: reason?.trim() || null } };
    f.character_slug = slug;
    f.status = decision === 'skip' ? 'skipped' : f.status === 'analysed' || f.status === 'approved' ? f.status : 'approved';
    this.emit('favorites');
  }

  async addOwnerLink(url: string, characterSlug: string, note: string | null) {
    const { platform, url: canonical } = canonicalVideoUrl(url);
    const existing = this.favs.find((f) => f.url === canonical);
    const decision = { decision: 'approve', by: 'owner', reason: "owner's own favourite" };
    if (existing) {
      if (existing.status === 'new' || existing.status === 'skipped') {
        const { hold_reason: _drop, ...rest } = existing.proposal;
        void _drop;
        existing.proposal = { ...rest, decision };
        existing.status = 'approved';
        if (note?.trim()) existing.note = note.trim();
        this.emit('favorites');
      }
      return { duplicate: true };
    }
    this.favs.push({
      id: uid('fo'), url: canonical, platform, creator_handle: null, views: null, outlier_x: null, origin: 'owner',
      character_slug: characterSlug, proposal: { decision }, scores: {}, total_score: null, note: note?.trim() || null,
      status: 'approved', created_at: new Date(this.now()).toISOString(), clip_id: null,
    });
    this.emit('favorites');
    return { duplicate: false };
  }

  async signedUrl() {
    return null; // demo masters do not exist: the player shows a labelled stand-in frame
  }

  subscribe(onChange: (kind: ChangeKind) => void, onStatus: (up: boolean) => void) {
    this.listeners.add(onChange);
    queueMicrotask(() => onStatus(true));
    return () => {
      this.listeners.delete(onChange);
    };
  }
}
