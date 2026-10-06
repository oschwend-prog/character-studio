// Demo mode (?demo=1 or VITE_DEMO=1): the whole terminal on an in-memory studio, so the UI can be
// shown and verified without a live connection. The Viral Picks are the real batch-1 picks
// (docs/launch/viral-picks-2026-10-04.md, parsed by studio.seed); every clip, post, metric and credit
// figure is SYNTHETIC and the UI says so. Actions follow the same rules as the SQL RPCs.
import picksJson from './batch1-picks.json';
import traitsJson from './traits.json';
import { canonicalVideoUrl, AUTOPILOT_MIN_APPROVED, PROPS_MAX, PROP_MAX_CHARS, SCAN_DAYS, checkClipBasics, estimateCredits, ownerClipPath } from '../lib/rules';
import { validateAdjust } from '../lib/drop';
import { velocityPerDay } from '../lib/analyst';
import { decisionTime, inTracker } from '../lib/tracker';
import { londonDayKey, londonWallToIso } from '../lib/format';
import { orderRoster } from '../lib/roster';
import type {
  Backend, Budget, Channel, ChangeKind, Character, CharacterTraits, ClipAnalysis, ClipFile, ClipState, DecideExtras, DropAdjust, DropCard, Engagement, HealthRow, LibraryClip, OwnerMusic,
  Pick, PickHistory, Platform, PostStatus, QueueClip, RunRow, Snapshot, SourceCandidate, Tier, TrackerRow,
} from '../lib/types';

interface Account { id: string; character_slug: string; platform: Platform; handle: string; connected: boolean; mode: 'approval' | 'auto'; dropin_share: number }
interface Clip {
  id: string; character_slug: string; mode: 'dropin' | 'recreate'; state: ClipState; hook: string | null; caption: string | null;
  hashtags: string[]; master_path: string | null; cost: number | null; outlier_x: number | null; created_at: string;
  reject_reason: string | null; qa: QueueClip['qa']; features: Record<string, unknown>; source: { kind: string; url: string | null; credit: string | null; trend: string | null } | null;
  /** When the clip last moved (v_tracker works it out from the ledger and the posts); the creation time when absent. */
  state_since?: string;
}
interface Post { id: string; clip_id: string; account_id: string; scheduled_for: string; status: PostStatus; url: string | null; error: string | null; views: number | null; likes: number | null; comments: number | null; shares: number | null; saves: number | null; follows: number | null }
interface Fav {
  id: string; url: string; platform: string; creator_handle: string | null; views: number | null; outlier_x: number | null;
  origin: 'scan' | 'owner'; character_slug: string | null; proposal: Record<string, unknown>; scores: Record<string, number>;
  total_score: number | null; note: string | null; status: string; created_at: string; clip_id: string | null;
}

// The roster of 2026-10-06 (Franz, Reginald, Lenny Gold; the slots are the owner's) and Biscuit, retired (paused) with his history.
const NAMES: Record<string, string> = { franz: 'Franz', reginald: 'Reginald', lenny: 'Lenny Gold', biscuit: 'Biscuit' };
const SLOTS: Record<string, string> = { franz: '19:00', reginald: '19:30', lenny: '12:30', biscuit: '19:00' };
const STATUS: Record<string, string> = { franz: 'designing', reginald: 'live', lenny: 'designing', biscuit: 'paused' };
const BODIES: Record<string, string[]> = { franz: ['quadruped'], reginald: ['biped'], lenny: ['biped'], biscuit: ['biped', 'quadruped'] };
/** The handles each character's social kit plans (characters/<slug>/social.md), for the ones with no account yet. */
const PLANNED: Record<string, Record<string, string>> = {
  franz: { instagram: 'franz.dachshund', tiktok: '@franz.dachshund' },
  lenny: { instagram: 'lennygold.agent', tiktok: '@lennygold.agent' },
};
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

/** A 9:16 stand-in picture for a demo pick (an inline SVG: the demo makes no network request and stores no media). */
function demoThumb(label: string, hue: number): string {
  const svg =
    `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 90 160"><defs><linearGradient id="g" x1="0" y1="0" x2="1" y2="1">` +
    `<stop offset="0" stop-color="hsl(${hue} 55% 38%)"/><stop offset="1" stop-color="hsl(${(hue + 50) % 360} 60% 18%)"/></linearGradient></defs>` +
    `<rect width="90" height="160" fill="url(#g)"/><circle cx="45" cy="62" r="20" fill="hsl(${hue} 70% 80%)" opacity=".85"/>` +
    `<rect x="25" y="86" width="40" height="46" rx="14" fill="hsl(${hue} 70% 80%)" opacity=".7"/>` +
    `<text x="45" y="150" font-family="sans-serif" font-size="8" font-weight="700" fill="#fff" fill-opacity=".8" text-anchor="middle">${label}</text></svg>`;
  return `data:image/svg+xml;utf8,${encodeURIComponent(svg)}`;
}

/** A 16:9 stand-in picture (a YouTube Shorts thumbnail is landscape: the card letterboxes it in its 9:16 frame). */
function demoWide(label: string, hue: number): string {
  const svg =
    `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 160 90"><defs><linearGradient id="g" x1="0" y1="0" x2="1" y2="1">` +
    `<stop offset="0" stop-color="hsl(${hue} 50% 40%)"/><stop offset="1" stop-color="hsl(${(hue + 60) % 360} 55% 16%)"/></linearGradient></defs>` +
    `<rect width="160" height="90" fill="url(#g)"/><circle cx="80" cy="38" r="16" fill="hsl(${hue} 70% 82%)" opacity=".85"/>` +
    `<rect x="62" y="56" width="36" height="26" rx="10" fill="hsl(${hue} 70% 82%)" opacity=".7"/>` +
    `<text x="80" y="86" font-family="sans-serif" font-size="7" font-weight="700" fill="#fff" fill-opacity=".8" text-anchor="middle">${label}</text></svg>`;
  return `data:image/svg+xml;utf8,${encodeURIComponent(svg)}`;
}

const MUSIC_ARMS = ['in_app', 'original', 'ai_beat'];
const DEMO_JOB_MS = 2_000; // how long the demo's "cloud job" takes

/** v_tracker.drop_card (migration 0012): proposal.drop without the job's internals. */
function dropCardOf(f: { proposal: Record<string, unknown> }): DropCard | null {
  const d = f.proposal.drop;
  if (!d || typeof d !== 'object' || Array.isArray(d)) return null;
  const { deconstruct: _d, make: _m, job: _j, ...card } = d as Record<string, unknown>;
  void _d; void _m; void _j;
  return card as unknown as DropCard;
}

const ownerOf = (f: { proposal: Record<string, unknown> }) => ({
  owner_note: (f.proposal.owner_note as string) ?? null,
  owner_mode: (f.proposal.owner_mode as 'dropin' | 'recreate') ?? null,
  owner_presence: (f.proposal.owner_presence as 'cameo' | 'featured' | 'star') ?? null,
  owner_props: Array.isArray(f.proposal.owner_props) ? (f.proposal.owner_props as string[]) : null,
  owner_music: (f.proposal.owner_music as OwnerMusic) ?? null,
  owner_clip_path: (f.proposal.owner_clip_path as string) ?? null,
  tier: (f.proposal.tier as Tier) ?? null,
  theme: (f.proposal.theme as string) ?? null,
  posted_at: (f.proposal.posted_at as string) ?? null,
  gallery: f.proposal.source_kind === 'higgsfield_library' || String(f.proposal.preset_id ?? '').trim() !== '',
  thumbnail_url: (f.proposal.thumbnail_url as string) ?? null,
  preview_url: (f.proposal.preview_url as string) ?? null,
  velocity: typeof f.proposal.velocity === 'number' ? f.proposal.velocity : null,
  engagement: (f.proposal.engagement as Engagement) ?? null,
  saturation_count: typeof f.proposal.saturation_count === 'number' ? f.proposal.saturation_count : null,
  trait_matches: Array.isArray(f.proposal.trait_matches) ? (f.proposal.trait_matches as string[]) : null,
  why: (f.proposal.why as string) ?? null,
  analysis: (f.proposal.analysis as ClipAnalysis) ?? null,
  recognisability: typeof f.proposal.recognisability === 'number' ? f.proposal.recognisability : null,
  original_views: typeof f.proposal.original_views === 'number' ? f.proposal.original_views : null,
  original_url: (f.proposal.original_url as string) ?? null,
  source_status: (f.proposal.source_status as string) ?? null,
  audio_risk: (f.proposal.audio_risk as string) ?? null,
  est_credits: typeof f.proposal.est_credits === 'number' ? f.proposal.est_credits : null,
  season: (f.proposal.season as string) ?? null,
  checks: Array.isArray(f.proposal.checks) ? (f.proposal.checks as string[]) : null,
  source_candidates: Array.isArray(f.proposal.source_candidates) ? (f.proposal.source_candidates as SourceCandidate[]) : null,
});

export class DemoBackend implements Backend {
  readonly kind = 'demo' as const;
  private accounts: Account[] = [];
  private clips: Clip[] = [];
  private posts: Post[] = [];
  private favs: Fav[] = [];
  private runs: RunRow[] = [];
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
    const btt = acc('biscuit', 'tiktok', '@biscuit.moves', 'approval', 1);
    const big = acc('biscuit', 'instagram', 'biscuit.moves', 'auto', 1);
    const rtt = acc('reginald', 'tiktok', '@reginald.thebutler', 'approval', 1);
    const rig = acc('reginald', 'instagram', 'reginald.thebutler', 'approval', 1);

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
      cost: 84, caption: 'Eye check · dachshund edition\nblue one sees the beat. amber one sees you. 🌭\nwhich eye did you notice first? 💙\n🎵 original beat',
      hashtags: ['#dachshund', '#dogdance', '#sausagedog', '#oddeyes'],
      features: { format_id: 'B-EYELOOP', hook_text: "eyes don't match. moves do.", seamless_loop: true, first_comment: 'which eye did you notice first? 💙🧡' },
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
      ['B1', 'reginald', 'first day as head butler', 162,
        'First day on the job · butler edition\nNobody saw the tray move. 🎩\nSend this to whoever starts somewhere new on Monday.\n🎵 trend: @eatfryhaven #butler #deadpan #firstday #oddeyes'],
      ['B2', 'reginald', 'POV: you rang for tea', 158,
        'Tea time · butler edition\nThe bell can wait. The kettle cannot. 🫖\nWhich would you ring for first?\n🎵 trend: @drink321coffee #butler #deadpan #teatime #oddeyes'],
      ['D6', 'biscuit', 'official taste inspector', 171, 'croissant: approved. crumbs: also approved. #dachshund #sausagedog'],
    ];
    queued.forEach(([ref, slug, hook, cost, caption], i) => {
      const f = pickByRef.get(ref)!;
      const c = clip(slug, hook, 'recreate', 'awaiting_approval', 0, {
        cost, caption: caption.replace(/\s*#\w+/g, '').trim(), hashtags: caption.match(/#\w+/g) ?? [],
        created_at: new Date(now - (3 - i) * 3600_000).toISOString(),
        features: {
          format_id: slug === 'biscuit' ? 'B-EGO' : 'R-DEADPAN', hook_text: hook, fav_id: f.id,
          ...(i < 2 ? { first_comment: slug === 'biscuit' ? 'which eye did you notice first? 💙🧡' : 'Requests for next week may be left below. Within reason.' } : {}),
        },
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

    // What the owner said in the "Make it" sheet on a few picks that are approved and waiting to be made.
    const said = (ref: string, owner: Record<string, string>) => {
      const f = pickByRef.get(ref);
      if (f) f.proposal = { ...f.proposal, ...owner };
    };
    said('D2', { owner_mode: 'dropin', owner_presence: 'featured', owner_note: 'keep the snare hits on the beat' });
    said('B3', { owner_mode: 'dropin', owner_presence: 'cameo', owner_note: 'the tea stays in frame' });
    said('D5', { owner_mode: 'recreate' });
    // one proposed pick with the owner's gadgets & jewellery, and a music choice
    (pickByRef.get('D2')!.proposal as Record<string, unknown>).owner_props = ['gold chain', 'aviator shades'];
    (pickByRef.get('D2')!.proposal as Record<string, unknown>).owner_music = 'in_app';
    (pickByRef.get('B3')!.proposal as Record<string, unknown>).owner_props = ['gold pocket watch'];

    // The pick card (migration 0008): which scan theme each pick matched, when it was posted (what the derived tier reads),
    // an explicit tier where the analyst set one, and a picture. The pictures are inline stand-ins: B5 has an expired
    // platform link and B6 none, so the placeholder tile shows too.
    const DAYS = 86_400_000;
    const posted = (d: number) => new Date(now - d * DAYS).toISOString();
    const card = (ref: string, c: Record<string, unknown>) => {
      const f = pickByRef.get(ref);
      if (f) f.proposal = { ...f.proposal, ...c };
    };
    card('B1', { theme: 'false premise, then the drop', posted_at: posted(21), thumbnail_url: demoThumb('DEMO', 215) });
    card('B2', { theme: 'deadpan at work', posted_at: posted(9), thumbnail_url: demoThumb('DEMO', 150) });
    card('B3', {
      theme: 'deadpan at work', posted_at: posted(8), thumbnail_url: demoThumb('DEMO', 40),
      analysis: { people_count: 1, main_subject: 'a waiter with a tray', camera: 'static', watermark: false, overlay: false, minors: false, best_window: { start_s: 2, end_s: 9.5 }, bpm: 104 },
    });
    card('D2', { theme: 'stare, then hits every beat', posted_at: posted(11), thumbnail_url: demoThumb('DEMO', 200) });
    card('D4', { theme: 'stare, then hits every beat', posted_at: posted(3), thumbnail_url: demoThumb('DEMO', 190) });
    card('D5', { theme: 'skilled upright dance', posted_at: posted(2), thumbnail_url: demoThumb('DEMO', 280) });
    card('D6', { theme: 'pet with a human job', posted_at: posted(5), thumbnail_url: demoThumb('DEMO', 25) });
    card('D1', { tier: 'iconic', theme: 'dog leads the dancers', posted_at: posted(6), thumbnail_url: demoThumb('DEMO', 330) });
    card('D3', {
      source_kind: 'higgsfield_library', preset_id: 'hf-genjutsu-pets-04', theme: 'skilled upright dance', posted_at: posted(4),
      thumbnail_url: demoThumb('GENJUTSU', 170),
    });
    card('B4', { theme: 'deadpan at work', posted_at: posted(2), thumbnail_url: demoThumb('DEMO', 100) });
    card('B5', {
      theme: 'elder out-dances the young', posted_at: posted(6), thumbnail_url: 'https://p16-sign.tiktokcdn.com/obj/expired-demo-link.jpg',
    });
    card('B6', { theme: 'elder out-dances the young', posted_at: posted(5) });
    for (const ref of ['O1', 'O2', 'O3', 'O4', 'O5']) card(ref, { posted_at: posted(12), thumbnail_url: demoThumb('DEMO', 260) });

    // The analyst's data (migration 0009), SYNTHETIC like everything here: age comes from posted_at, the stored velocity is what the
    // scan worked out when it filed the pick (views per day since posting), then reactions, how crowded the idea is, the traits it
    // matches, the analyst's reasoning and, for the ones already looked at, the check of the clip. Some picks carry none of it.
    const vel = (views: number, days: number) => velocityPerDay(views, days) ?? 0;
    card('D1', {
      velocity: vel(2_000_000, 6), engagement: { likes: 168_000, comments: 3_100, shares: 22_000, saves: 9_400 }, saturation_count: 2,
      trait_matches: ['dog leads the dancers', 'bouncy and puppy-cute'],
      why: 'Biscuit takes the front-and-centre spot of a human dance crew: one animal is the star, full body, static camera. Only the lead is swapped; the backup dancers stay as the scene.',
      analysis: {
        people_count: 4, main_subject: 'the lead dancer, to be swapped for Biscuit', camera: 'static', watermark: false, overlay: false, minors: false,
        best_window: { start_s: 1.5, end_s: 9.5 }, bpm: 118, notes: 'Four dancers; swap the lead only. One cut at 11 s, outside the window.',
      },
    });
    card('D3', {
      trait_matches: ['slick upright dance'],
      why: 'A ready-made drop-in from the Genjutsu gallery: one performer, static camera, upright dance. It costs no search credits.',
      analysis: {
        people_count: 1, main_subject: 'a small dog dancing upright', camera: 'static', watermark: false, overlay: false, minors: false,
        best_window: { start_s: 0, end_s: 8 }, bpm: 124, notes: 'Gallery clip: already clean and trimmed.',
      },
    });
    card('B4', {
      velocity: vel(22_300_000, 2), engagement: { likes: 2_100_000, comments: 31_000, shares: 410_000, saves: 180_000 }, saturation_count: 5,
      trait_matches: ['calm and dignified', 'a straight face under absurdity'],
      why: 'A straight face while the room falls apart is Reginald’s whole joke. One performer, mostly static camera; whatever burns or breaks behind him is replaced by our scene.',
    });
    card('B5', {
      velocity: vel(2_900_000, 6), engagement: { likes: 240_000, comments: 5_200, shares: 41_000 }, saturation_count: 9,
      trait_matches: ['formal elder out-dances the young'],
      why: 'The elder who out-dances the young is a Reginald format, but nine near copies landed this week: the idea is crowded, so the fresh angle has to be the quiff.',
    });
    card('B6', {
      velocity: vel(349_700, 5), engagement: { likes: 41_000, comments: 900, shares: 6_100, saves: 3_300 }, saturation_count: 0,
      trait_matches: ['uniform at work plus a trend dance', 'the quiff stays rigid'],
      why: 'Nobody else has this angle yet. A uniform at work and a trend dance is his best format; the creator’s handle is burned in, so it is made as a Recreate.',
      analysis: {
        people_count: 3, main_subject: 'a butler among partygoers', camera: 'handheld', watermark: true, overlay: false, minors: false,
        best_window: { start_s: 2, end_s: 9.5 }, bpm: null, notes: 'The creator’s handle is burned in at the bottom left.',
      },
    });
    card('O1', { velocity: vel(5_700_000, 12), saturation_count: 1 });

    // The long list (migration 0010), SYNTHETIC: how recognisable an iconic moment is and its original's views, the clip and audio
    // situation, the analyst's estimate, the season, the checks and the clean-clip candidates. Some picks have none of it, so the
    // terminal's own estimate and the empty cells show too.
    card('D1', {
      recognisability: 7, est_credits: 160, source_status: 'needs a clean clip (recreate fallback)', audio_risk: 'original/low',
      checks: ['four dancers: swap the lead only', 'credit the crew in the caption'],
    });
    card('B4', { source_status: 'clip itself is the source', audio_risk: 'unidentified track: check before posting, fallback in-app', est_credits: 91 });
    card('B5', { source_status: 'needs a clean clip (recreate fallback)', checks: ['nine near copies this week: lead with the quiff'] });

    // Four stand-in picks (SYNTHETIC, like every clip here) so each tier has a card for both characters.
    const standIn = (n: number, slug: string, platform: string, handle: string, hook: string, concept: string, views: number, x: number, total: number, proposal: Record<string, unknown>): Fav => {
      const f: Fav = {
        id: uid(`fs${n}`), origin: 'scan', status: 'new', clip_id: null, character_slug: slug, platform, creator_handle: handle, views, outlier_x: x,
        url: platform === 'youtube' ? `https://www.youtube.com/shorts/demoSynth${n}` : platform === 'higgsfield' ? 'higgsfield-preset:hf-genjutsu-butler-02' : `https://www.${platform}.com/${platform === 'tiktok' ? `@${handle.slice(1)}/video/76000000000000000${n}` : `reel/DemoSynth${n}/`}`,
        scores: { virality: 8, reach: 7, freshness: 8, fit: 8, feasibility: 8, saturation: 6 }, total_score: total,
        note: 'SYNTHETIC demo pick', created_at: new Date(now - 20 * 3600_000 + n * 60_000).toISOString(),
        proposal: { mode: 'dropin', hook, concept, ...proposal },
      };
      this.favs.push(f);
      return f;
    };
    standIn(1, 'biscuit', 'tiktok', '@demo.pawprint', 'tracksuit on. worries off.', 'Small dog in a tracksuit mouths the lyric, one paw on the beat; the caption gives him a job.', 3_100_000, 1240, 78, {
      theme: 'pet with a human job', posted_at: posted(3), thumbnail_url: demoThumb('DEMO', 300),
      est_credits: 91, source_status: 'clip itself is the source', audio_risk: 'original/low', checks: ['credit the creator in the caption'],
      decision: { decision: 'approve', by: 'analyst', reason: 'Matches: wholesome ego, ego or job caption. Posted 3 days ago at 1,240x.' },
      velocity: vel(3_100_000, 3), engagement: { likes: 322_000, comments: 6_400, shares: 58_000, saves: 21_000 }, saturation_count: 3,
      trait_matches: ['wholesome ego', 'ego or job caption', 'slick upright dance'],
      why: 'A tiny dog with a main-character job caption: exactly the wholesome ego. One animal, full body, static camera; three near copies this week, so still fresh.',
      analysis: {
        people_count: 0, main_subject: 'a dachshund in a tracksuit', camera: 'static', watermark: false, overlay: false, minors: false,
        best_window: { start_s: 2.5, end_s: 10, }, bpm: 112.5, notes: 'Clean start, one hard cut at 11 s: use the first 10 s.',
      },
    });
    standIn(2, 'biscuit', 'instagram', '@demo.doxie', 'vet face. fully fine.', 'Stares into the lens, then hits one perfect beat; rewatch bait.', 38_000, 18, 71, {
      theme: 'stare, then hits every beat', posted_at: posted(1), thumbnail_url: demoThumb('DEMO', 80),
      velocity: vel(38_000, 1), engagement: { likes: 3_100, comments: 190 }, saturation_count: 0,
      trait_matches: ['head-snap into the lens'],
    });
    standIn(3, 'reginald', 'youtube', '@demo.rainstreet', 'an umbrella. a puddle. no notes.', 'A formal figure dances with an umbrella in the rain, perfectly serious; a famous scene, played straight.', 12_000_000, 5.2, 69, {
      mode: 'recreate', tier: 'iconic', theme: 'one action, new location', posted_at: posted(400), thumbnail_url: demoWide('DEMO', 215),
      recognisability: 9, original_views: 1_359_825_767, original_url: 'https://www.youtube.com/watch?v=demoSynth03', est_credits: 160,
      source_status: 'needs a clean clip (recreate fallback)', audio_risk: 'chart song: Instagram may mute it, fallback in-app', season: 'rainy autumn weeks',
      checks: ['no real-person likeness: the moves only, never the original look', 'the same moment is Biscuit’s later pick: not in the same fortnight'],
      source_candidates: [
        { id: 'demoTut0001', views: 48_000, published: '2024-03-02', why: 'a solo tutorial: preview it for on-screen text' },
        { id: 'demoTut0002', views: 2_100_000, published: '2019-11-20', why: 'probably carries a studio logo, so probably not clean' },
      ],
      decision: { decision: 'approve', by: 'analyst', reason: 'Matches: deadpan under absurdity, black umbrella. A famous moment everyone knows.' },
      engagement: { likes: 410_000, comments: 8_800 },
      trait_matches: ['deadpan under absurdity', 'black umbrella'],
      why: 'A famous scene played completely straight is the Reginald joke. It is an iconic evergreen moment, so it is made as a Recreate with a synthetic driver.',
    });
    standIn(4, 'reginald', 'higgsfield', '@genjutsu', 'tea for two, dance for one', 'A Genjutsu gallery clip: one dancer, static camera, ready to drop in.', 380_000, 9.1, 66, {
      source_kind: 'higgsfield_library', preset_id: 'hf-genjutsu-butler-02', theme: 'deadpan at work', posted_at: posted(8), thumbnail_url: demoThumb('GENJUTSU', 160),
    });

    // Clips still being made: the "In production" stage of the pipeline.
    const hour = 3600_000;
    const generating = clip('biscuit', 'smooth operator, small dog', 'recreate', 'generating', 0, { master_path: null, cost: 98, created_at: new Date(now - 2 * hour).toISOString() });
    const planned = clip('biscuit', 'tiny tux, big feelings', 'dropin', 'planned', 0, { master_path: null, cost: null, created_at: new Date(now - 0.5 * hour).toISOString() });
    const quiff = clip('reginald', 'the quiff moved. we do not speak of it.', 'recreate', 'qa_failed', 0, {
      master_path: null, cost: 162, created_at: new Date(now - 5 * hour).toISOString(),
      qa: { tech: 'ok', problems: ['the quiff moves at 4 s'], visual: 'quiff flickers, smile at 6 s' },
    });

    // "In the works" (migration 0010): approved picks on their way to being posted, SYNTHETIC like every clip here. With the batch-1
    // picks above (D2 approved a day ago with no clip yet, D5 a Recreate, B1/B2/D6 waiting for your OK, D4 booked for 19:00) they
    // cover every step of the tracker and every flag: no clip yet, stuck, each failure, a dropped clip, and a post older than a week
    // that has dropped off.
    const at = (h: number) => new Date(now - h * hour).toISOString();
    const work = (k: number, slug: string, status: string, hook: string, concept: string, approvedHoursAgo: number, proposal: Record<string, unknown> = {}): Fav => {
      const f: Fav = {
        id: uid(`fw${k}`), url: `https://www.instagram.com/reel/DemoWork${k}/`, platform: 'instagram', creator_handle: `@demo.work${k}`,
        views: 1_200_000 + k * 310_000, outlier_x: 40 + k * 7, origin: 'scan', character_slug: slug,
        scores: { virality: 8, reach: 7, freshness: 8, fit: 8, feasibility: 8, saturation: 8 }, total_score: 80 + (k % 7),
        note: null, status, created_at: at(approvedHoursAgo), clip_id: null,
        proposal: {
          mode: 'dropin', hook, concept, posted_at: posted(3 + (k % 5)), thumbnail_url: demoThumb('DEMO', (k * 47) % 360),
          theme: slug === 'biscuit' ? 'skilled upright dance' : 'deadpan at work',
          decision: { decision: 'approve', by: 'rule', reason: 'rule: total 84 >= 80 and feasibility 8 >= 7' }, ...proposal,
        },
      };
      this.favs.push(f);
      return f;
    };
    const link = (f: Fav, c: Clip) => {
      f.clip_id = c.id;
      c.features = { ...c.features, fav_id: f.id };
    };
    const byHook = (hook: string) => this.clips.find((c) => c.hook === hook)!;
    work(1, 'biscuit', 'approved', 'tracksuit, but make it formal', 'Small dog in a tiny tracksuit does the shoulder-shimmy trend on a sunlit rug.', 2);
    work(2, 'reginald', 'approved', 'the gallery has spoken', 'A Genjutsu gallery clip: one dancer in a hallway, static camera; Reginald takes the moves.', 20, {
      source_kind: 'higgsfield_library', preset_id: 'hf-genjutsu-hallway-07', tier: 'gallery', thumbnail_url: demoThumb('GENJUTSU', 120),
    });
    link(work(3, 'biscuit', 'queued', 'smooth operator, small dog', 'A slow strut down a pastel corridor, one eyebrow raised; the glint on the last beat.', 28, { mode: 'recreate' }), generating);
    link(work(4, 'biscuit', 'queued', 'tiny tux, big feelings', 'Biscuit in a tiny tux takes the lead of a wedding dance-off.', 27), planned);
    link(work(5, 'reginald', 'queued', 'the quiff moved. we do not speak of it.', 'The butler irons a newspaper, then the beat drops into a deadpan robot.', 30, { mode: 'recreate' }), quiff);
    this.settled[quiff.id] = 162;
    link(work(6, 'reginald', 'queued', 'polishing the beat', 'Silver polishing in time with the snare, never a smile.', 33),
      clip('reginald', 'polishing the beat', 'dropin', 'generating', 0, { master_path: null, cost: 91, created_at: at(9), state_since: at(9) }));
    link(work(7, 'biscuit', 'queued', 'paws up, chin up', 'Paws up on every chorus hit, chin to the lens on the last one.', 31),
      clip('biscuit', 'paws up, chin up', 'dropin', 'gen_failed', 0, { master_path: null, cost: 91, created_at: at(4), state_since: at(3), qa: {} }));
    const generated = clip('reginald', 'tea, then chaos', 'dropin', 'generated', 0, { master_path: null, cost: 91, created_at: at(8), state_since: at(7), qa: {} });
    link(work(8, 'reginald', 'queued', 'tea, then chaos', 'He pours tea while the room behind him falls apart in time with the beat.', 34), generated);
    this.settled[generated.id] = 91;
    const built = clip('biscuit', 'one paw, one beat', 'dropin', 'mastered', 0, { cost: 91, created_at: at(3), state_since: at(1) });
    link(work(9, 'biscuit', 'queued', 'one paw, one beat', 'One paw taps every snare, the tail keeps the hi-hat.', 26), built);
    this.settled[built.id] = 91;
    const rejected = clip('reginald', 'the bow that went too far', 'dropin', 'rejected', 0, {
      cost: 91, created_at: at(30), state_since: at(6), reject_reason: 'the eyes are the wrong way round at 7 s',
    });
    link(work(10, 'reginald', 'made', 'the bow that went too far', 'A formal bow that turns into the trend’s floor move.', 50), rejected);
    this.settled[rejected.id] = 91;
    link(work(11, 'biscuit', 'made', 'going as myself this year', 'Biscuit in his hot-dog-bun costume does the spooky-season shuffle.', 60, { mode: 'recreate' }), byHook('going as myself this year'));
    link(work(12, 'reginald', 'made', 'everything is fine, sir', 'He sets the table while the kitchen floods, in time with the beat.', 70, { mode: 'recreate' }), byHook('everything is fine, sir'));
    const failedPost = clip('biscuit', 'sausage in a suit', 'dropin', 'scheduled', 1, { cost: 91, state_since: at(20) });
    link(work(13, 'biscuit', 'made', 'sausage in a suit', 'A tiny suit, a big dance: the lead of the office-party trend.', 48), failedPost);
    this.settled[failedPost.id] = 91;
    post(failedPost, btt, 0, 'scheduled', null, { scheduled_for: at(2) });
    post(failedPost, big, 0, 'failed', null, { scheduled_for: at(2), error: 'Instagram refused the upload twice (Postiz 500): retry or resolve it' });
    const dropped = clip('reginald', 'a smile at 6 s', 'dropin', 'dropped', 1, {
      master_path: null, cost: 91, state_since: at(22), qa: { tech: 'ok', problems: ['smile at 6 s', 'the quiff moves at 8 s'] },
    });
    link(work(14, 'reginald', 'approved', 'a smile at 6 s', 'Deadpan waltz with a mop; the second try keeps the straight face.', 40), dropped);
    this.settled[dropped.id] = 182;
    link(work(15, 'biscuit', 'made', "my eyes don't match. my moves do.", 'The first post: the eye close-up loop.', 24 * 14, { mode: 'recreate' }), byHook("my eyes don't match. my moves do."));

    // "Drop a video" (migration 0012): the owner's own drops, SYNTHETIC like every clip here, one in every state of a drop card:
    // uploading, checking, waiting (a link the cloud could not fetch), ready (a vertical clip and a landscape one with a crop),
    // blocked (a watermark, the wrong star), making (before its clip, waiting for a key; and with its clip generating), made
    // (waiting for your OK) and failed (the quality check failed twice).
    const minute = 60_000;
    const atMin = (m: number) => new Date(now - m * minute).toISOString();
    const dropFav = (k: number, slug: string, minutesAgo: number, drop: Record<string, unknown>, extra: Partial<Fav> = {}): Fav => {
      const id = uid(`fd${k}`);
      const link = typeof extra.url === 'string';
      const f: Fav = {
        id, url: `owner-drop:${id}`, platform: 'drop', creator_handle: null, views: null, outlier_x: null, origin: 'owner',
        character_slug: slug, scores: {}, total_score: null, note: null, status: 'approved', created_at: atMin(minutesAgo), clip_id: null,
        ...extra,
        proposal: {
          decision: { decision: 'approve', by: 'owner', reason: "owner's own video", at: atMin(minutesAgo) },
          ...(extra.proposal ?? {}),
          drop: { state: 'uploading', kind: link ? 'link' : 'file', at: atMin(minutesAgo), reason: null, own_footage: false, ...drop },
        },
      };
      this.favs.push(f);
      return f;
    };
    const checked = (id: string, o: { slug: string; star: DropCard['star']; seconds: number; start: number; duration: number; landscape?: boolean; hooks: string[]; gadgets: string[]; part?: string }) => ({
      source_id: uid('sd'), duration_s: o.duration, width: o.landscape ? 1920 : 1080, height: o.landscape ? 1080 : 1920, has_audio: true,
      window: { start_s: o.start, length_s: o.seconds }, crop_x: o.landscape ? o.star?.x_center ?? 0.5 : null, star: o.star, classic: o.seconds >= 12,
      part: o.part ?? 'featured', gadgets: o.gadgets, hooks: o.hooks, hook: o.hooks[0], music: 'original', seconds: o.seconds,
      credits: estimateCredits('dropin', o.seconds, 'original'), preview_path: `owner/${id}/preview.jpg`,
    });
    const person = (description: string, x = 0.5): DropCard['star'] => ({ kind: 'person', body: 'biped', description, x_center: x, full_body: true });
    const dog = (description: string, body: 'biped' | 'quadruped' = 'quadruped'): DropCard['star'] => ({ kind: 'dog', body, description, x_center: 0.5, full_body: true });
    const readyDrop = (k: number, slug: string, minutesAgo: number, concept: string, o: Parameters<typeof checked>[1], state = 'ready', drop: Record<string, unknown> = {}) => {
      const f = dropFav(k, slug, minutesAgo, {});
      f.proposal = {
        ...f.proposal, mode: 'dropin', owner_mode: 'dropin', hook: o.hooks[0], concept,
        drop: { ...(f.proposal.drop as Record<string, unknown>), ...checked(f.id, o), state, at: atMin(minutesAgo - 3), ...drop },
      };
      return f;
    };
    dropFav(1, 'biscuit', 2, { state: 'uploading' });
    dropFav(2, 'reginald', 4, { state: 'checking' });
    dropFav(3, 'biscuit', 180, { state: 'waiting', reason: 'the link could not be fetched in the cloud (login required): the Mac’s daily run tries again' }, {
      url: 'https://www.tiktok.com/@demo.dropdancer/video/7700000000000000001', platform: 'tiktok', creator_handle: '@demo.dropdancer',
    });
    readyDrop(4, 'biscuit', 40, 'A dachshund trots across a sunlit kitchen and spins on the beat.', {
      slug: 'biscuit', star: dog('the dachshund on the kitchen floor'), seconds: 9, start: 1.5, duration: 14.2,
      hooks: ['kitchen is my stage', 'chef’s kiss, but with paws', 'the spin was not planned'], gadgets: ['gold chain'],
    }, 'ready', { own_footage: true }); // the owner's own recording
    readyDrop(5, 'reginald', 25, 'A man in a grey suit does the shoulder shimmy down an office corridor.', {
      slug: 'reginald', star: person('the man in the grey suit in the middle', 0.42), seconds: 12.5, start: 3, duration: 31, landscape: true,
      hooks: ['The household is unaware.', 'Breakfast is at eight.', 'Kindly do not tell the Duchess.'], gadgets: ['silver tray + teapot'],
    });
    readyDrop(6, 'reginald', 90, 'Two friends film a dance in a car park; a watermark sits in the corner.', {
      slug: 'reginald', star: person('the man on the left'), seconds: 8, start: 0, duration: 11, hooks: ['a', 'b', 'c'], gadgets: [],
    }, 'blocked', { reason: 'a watermark or creator handle is burned in: paste the link instead', credits: undefined, window: undefined });
    dropFav(7, 'reginald', 70, { state: 'blocked', reason: 'the wrong star: Reginald replaces a person, this clip’s star is a dog' });
    const waitingKey = readyDrop(8, 'biscuit', 300, 'A pug walks a tightrope of sofa cushions, deadly serious.', {
      slug: 'biscuit', star: dog('the pug on the cushions'), seconds: 8.5, start: 2, duration: 12, hooks: ['balance is a lifestyle', 'x', 'y'], gadgets: [],
    }, 'making', { reason: 'waiting for the Higgsfield key: the next daily run makes it by hand' });
    waitingKey.proposal = { ...waitingKey.proposal, make_requested: { at: atMin(60), by: 'owner' } };
    const makingFav = readyDrop(9, 'reginald', 200, 'A man in an apron does the trend in a narrow kitchen.', {
      slug: 'reginald', star: person('the man in the apron'), seconds: 9, start: 1, duration: 16, hooks: ['Dinner is served. Eventually.', 'x', 'y'], gadgets: ['feather duster'],
    }, 'making', { reason: 'Higgsfield is still working (in_progress): the next run checks again' });
    makingFav.proposal = { ...makingFav.proposal, make_requested: { at: atMin(50), by: 'owner' } };
    makingFav.status = 'queued';
    link(makingFav, clip('reginald', 'Dinner is served. Eventually.', 'dropin', 'generating', 0, {
      master_path: null, cost: 102, created_at: atMin(45), state_since: atMin(44), qa: {},
    }));
    const madeFav = readyDrop(10, 'biscuit', 600, 'A dog in a hoodie does the hip-hop step on a skate ramp.', {
      slug: 'biscuit', star: dog('the dog in the hoodie', 'biped'), seconds: 9, start: 0.5, duration: 13, hooks: ['ramp? i own it.', 'x', 'y'], gadgets: [],
    }, 'made');
    madeFav.proposal = { ...madeFav.proposal, make_requested: { at: atMin(400), by: 'owner' } };
    madeFav.status = 'made';
    const madeClip = clip('biscuit', 'ramp? i own it.', 'dropin', 'awaiting_approval', 0, {
      cost: 102, created_at: atMin(380), state_since: atMin(60),
      caption: 'Skate ramp step · dachshund edition\nramp? i own it. 💙\nwhich eye did you notice first?',
      hashtags: ['#skaterdog', '#dachshund', '#dogdance', '#oddeyes'],
    });
    madeClip.features = { ...madeClip.features, first_comment: 'which eye did you notice first? 💙🧡', music: 'original', drop: true };
    link(madeFav, madeClip);
    this.settled[madeClip.id] = 102;
    const failedFav = readyDrop(11, 'reginald', 900, 'A woman in a red coat dances in the rain under a lamppost.', {
      slug: 'reginald', star: person('the woman in the red coat'), seconds: 12, start: 4, duration: 20, hooks: ['Umbrellas are for amateurs.', 'x', 'y'], gadgets: ['black umbrella'],
    }, 'failed', { reason: 'the quality check failed twice: the original woman is still dancing at 3 s' });
    const failedClip = clip('reginald', 'Umbrellas are for amateurs.', 'dropin', 'dropped', 0, {
      master_path: null, cost: 135, created_at: atMin(800), state_since: atMin(700),
      reject_reason: 'the quality check failed twice: the original woman is still dancing at 3 s',
    });
    link(failedFav, failedClip);
    this.settled[failedClip.id] = 270;
    // the roster's newcomers (2026-10-06): a checked drop for Franz (a dog star) and one being checked, and one for Lenny (a human star)
    readyDrop(12, 'franz', 15, 'A dachshund refuses the walk, then betrays himself into a tiny shuffle on a cream rug.', {
      slug: 'franz', star: dog('the dachshund on the cream rug'), seconds: 9, start: 1, duration: 12,
      hooks: ['One does not walk. One arrives.', 'I was stretching to music.', 'Fetch it yourself.'], gadgets: ['tortoiseshell sunglasses'],
    });
    dropFav(13, 'franz', 6, { state: 'checking' });
    readyDrop(14, 'lenny', 35, 'A man in a suit yells into his phone in a glass office, then hits the trend.', {
      slug: 'lenny', star: person('the man in the navy suit by the window', 0.46), seconds: 8.5, start: 0.5, duration: 11,
      hooks: ['NOON. Not 12:01.', 'Call my assistant.', 'You’re welcome.'], gadgets: ['black smartphone'],
    });

    // The run log: a finished scan on the latest scan day, an earlier one, and a day that did not scan.
    const scanDays = SCAN_DAYS;
    const at0800 = (back: number) => londonWallToIso(`${londonDayKey(now - back * DAY)}T08:00`);
    const weekday = (iso: string) => new Intl.DateTimeFormat('en-GB', { timeZone: 'Europe/London', weekday: 'short' }).format(new Date(iso));
    const past = [0, 1, 2, 3, 4, 5, 6, 7].map(at0800).filter((iso) => Date.parse(iso) + 45 * 60_000 < now);
    const scanAt = past.filter((iso) => scanDays.includes(weekday(iso)));
    const run = (started: string, minutes: number, details: RunRow['details'], summary: string): RunRow => ({
      id: uid('r'), kind: 'daily', started_at: started, finished_at: new Date(Date.parse(started) + minutes * 60_000).toISOString(),
      status: 'ok', summary, details,
    });
    if (scanAt[0]) {
      this.runs.push(run(scanAt[0], 41, {
        scan: {
          queries: ['biscuit #2 concept'], outliers: 18, picks_added: 4, auto_approved: 1, held: 1, skipped: 2,
          vidiq_credits: 5,
        },
      }, 'SYNTHETIC: 2 clips made, 4 picks filed'));
    }
    if (scanAt[1]) {
      this.runs.push(run(scanAt[1], 33, {
        scan: { queries: ['reginald #4 concept'], outliers: 14, picks_added: 3, auto_approved: 2, held: 0, skipped: 1, vidiq_credits: 5 },
      }, 'SYNTHETIC: 2 clips made, 3 picks filed'));
    }
    const noScan = past.find((iso) => !scanDays.includes(weekday(iso)));
    if (noScan) this.runs.push(run(noScan, 22, {}, 'SYNTHETIC: 1 clip made'));
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
    return c.mode === 'recreate' ? connected : connected.filter((a) => a.dropin_share >= 1 || this.dropinRatio(a.id, c.id) < a.dropin_share); // a share of 1 is no cap
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

  /** The demo's cloud jobs, worked out lazily from the time (so tests drive them with the clock): a check requested over 2 s ago
   * is ready, a Make it over 2 s ago has its clip generating. */
  private tick() {
    const now = this.now();
    for (const f of this.favs) {
      const d = f.proposal.drop as Record<string, unknown> | undefined;
      if (!d || typeof d !== 'object') continue;
      const req = (d.requested ?? {}) as { process?: string; make?: string };
      if (d.state === 'checking' && req.process && now - Date.parse(req.process) >= DEMO_JOB_MS) {
        const slug = f.character_slug ?? 'biscuit';
        const star: DropCard['star'] = slug === 'biscuit' ? { kind: 'dog', body: 'quadruped', description: 'the dog in the middle', x_center: 0.5, full_body: true }
          : { kind: 'person', body: 'biped', description: 'the person in the middle', x_center: 0.5, full_body: true };
        const seconds = 9;
        const hooks = slug === 'biscuit' ? ['main character energy', 'the beat asked for me', 'one take. obviously.'] : ['The household is unaware.', 'Breakfast is at eight.', 'Kindly do not tell the Duchess.'];
        f.proposal = {
          ...f.proposal, mode: 'dropin', owner_mode: 'dropin', hook: hooks[0], concept: 'SYNTHETIC: your video, checked (the demo makes up what it found)',
          drop: {
            ...d, state: 'ready', reason: null, at: new Date(now).toISOString(), source_id: uid('sd'), duration_s: 14, width: 1080, height: 1920,
            window: { start_s: 1, length_s: seconds }, crop_x: null, star, classic: false, part: 'featured', gadgets: [], hooks, hook: hooks[0],
            music: 'original', seconds, credits: estimateCredits('dropin', seconds, 'original'), preview_path: `owner/${f.id}/preview.jpg`,
          },
        };
      }
      if (d.state === 'making' && req.make && now - Date.parse(req.make) >= DEMO_JOB_MS && !this.clips.some((c) => c.features.fav_id === f.id && c.state !== 'dropped')) {
        const hook = String((d.adjust as DropAdjust | undefined)?.hook ?? d.hook ?? 'demo');
        const c: Clip = {
          id: uid('cd'), character_slug: f.character_slug ?? 'biscuit', mode: 'dropin', state: 'generating', hook, caption: null, hashtags: [],
          master_path: null, cost: Number(d.credits ?? 0), outlier_x: null, created_at: new Date(now).toISOString(), reject_reason: null,
          qa: {}, features: { fav_id: f.id, drop: true, music: 'original' }, source: null,
        };
        this.clips.push(c);
        f.clip_id = c.id;
        f.status = 'queued';
      }
    }
  }

  async load(): Promise<Snapshot> {
    this.tick();
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
        account_id: a.id, character_slug: a.character_slug, character_name: NAMES[a.character_slug], character_status: STATUS[a.character_slug] ?? 'live',
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
          first_comment: typeof c.features.first_comment === 'string' ? c.features.first_comment : null,
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

    const bySlug: Record<string, number> = Object.fromEntries(Object.keys(NAMES).map((slug) => [slug, 0]));
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
        note: f.note, status: f.status, created_at: f.created_at, ...ownerOf(f),
      }));
    const history: PickHistory[] = this.favs
      .filter((f) => f.status !== 'new')
      .sort((a, b) => (b.total_score ?? 0) - (a.total_score ?? 0))
      .map((f) => ({
        id: f.id, url: f.url, platform: f.platform, creator_handle: f.creator_handle, views: f.views, outlier_x: f.outlier_x,
        origin: f.origin, character_slug: f.character_slug, character_name: name(f.character_slug), total_score: f.total_score,
        hook: (f.proposal.hook as string) ?? null, concept: (f.proposal.concept as string) ?? null,
        decision: (f.proposal.decision as PickHistory['decision']) ?? null, note: f.note, status: f.status, created_at: f.created_at,
        clip_id: f.clip_id, clip_state: f.clip_id ? this.clips.find((c) => c.id === f.clip_id)?.state ?? null : null, ...ownerOf(f),
      }));

    const characters: Character[] = orderRoster(Object.keys(NAMES).map((slug) => ({
      slug, name: NAMES[slug], status: STATUS[slug], bodies: BODIES[slug],
      setup: {
        closeup: true, // every character of the roster has his close-up (refs.json, 2026-10-06)
        planned_handles: {
          ...PLANNED[slug],
          ...Object.fromEntries(this.accounts.filter((a) => a.character_slug === slug).map((a) => [a.platform, a.handle])),
        },
        traits: (traitsJson as Record<string, CharacterTraits>)[slug] ?? null,
      },
      accounts: this.accounts.filter((a) => a.character_slug === slug).map((a) => ({ platform: a.platform, handle: a.handle, has_postiz: a.connected, mode: a.mode })),
    })));

    const tracker: TrackerRow[] = this.favs
      .filter((f) => ['approved', 'analysed', 'queued', 'made'].includes(f.status))
      .map((f) => this.trackerRow(f, name(f.character_slug)))
      .filter((r) => inTracker(r, now));

    return { channels, queue, library, budget, health, picks, history, characters, runs: this.runs.map((r) => ({ ...r })), tracker, loadedAt: now };
  }

  /** One v_tracker row (migration 0010): the pick, its newest clip, that clip's latest post (a problem first within a slot), the credits. */
  private trackerRow(f: Fav, characterName: string | null): TrackerRow {
    const mine = this.clips.filter((c) => c.id === f.clip_id || c.features.fav_id === f.id);
    const c = [...mine].sort((a, b) => Date.parse(b.created_at) - Date.parse(a.created_at) || b.id.localeCompare(a.id))[0] ?? null;
    const rank: Record<PostStatus, number> = { failed: 0, needs_check: 1, posting: 2, scheduled: 3, posted: 4 };
    const p = c
      ? this.posts
        .filter((x) => x.clip_id === c.id)
        .sort((a, b) => Date.parse(b.scheduled_for) - Date.parse(a.scheduled_for) || rank[a.status] - rank[b.status] || a.id.localeCompare(b.id))[0] ?? null
      : null;
    const problems = c && Array.isArray(c.qa.problems) && c.qa.problems.length ? c.qa.problems.join(' / ') : null;
    const error = c && typeof c.qa.error === 'string' && c.qa.error.trim() ? c.qa.error.trim() : null;
    const o = ownerOf(f);
    return {
      pick_id: f.id, character_slug: f.character_slug, character_name: characterName, url: f.url, platform: f.platform,
      creator_handle: f.creator_handle, views: f.views, outlier_x: f.outlier_x, tier: o.tier, theme: o.theme,
      concept: (f.proposal.concept as string) ?? null, hook: (f.proposal.hook as string) ?? null, thumbnail_url: o.thumbnail_url,
      preview_url: o.preview_url, gallery: o.gallery, posted_at: o.posted_at, velocity: o.velocity,
      proposed_mode: (f.proposal.mode as string) ?? null, owner_mode: o.owner_mode, owner_presence: o.owner_presence,
      owner_music: o.owner_music, owner_clip_path: o.owner_clip_path, status: f.status,
      decision: (f.proposal.decision as TrackerRow['decision']) ?? null,
      approved_at: decisionTime(f.proposal.decision as TrackerRow['decision'], f.created_at),
      decided_at: decisionTime(f.proposal.decision as TrackerRow['decision'], '') || null, note: f.note,
      source_id: (f.proposal.source_id as string) ?? null, analysis: o.analysis,
      fetch_failed: (f.proposal.fetch_failed as TrackerRow['fetch_failed']) ?? null,
      clip_id: c?.id ?? null, clip_state: c?.state ?? null, clip_mode: c?.mode ?? null,
      clip_state_since: c ? c.state_since ?? c.created_at : null,
      clip_failure: c ? c.reject_reason?.trim() || problems || error : null,
      credits_spent: mine.reduce((sum, x) => sum + (this.settled[x.id] ?? 0), 0),
      post_id: p?.id ?? null, post_status: p?.status ?? null, post_scheduled_for: p?.scheduled_for ?? null,
      post_posted_at: p?.status === 'posted' ? p.scheduled_for : null, post_url: p?.url ?? null, post_error: p?.error ?? null,
      latest_views: p?.views ?? null,
      caption: c?.caption ?? null,
      hashtags: c ? c.hashtags : null,
      first_comment: c && typeof c.features.first_comment === 'string' ? c.features.first_comment : null,
      drop_card: dropCardOf(f),
      make_requested_at: (f.proposal.make_requested as { at?: string } | undefined)?.at ?? null,
    };
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

  /** decide_pick of migration 0007: the same refusals, in the same order, and the same writes. */
  async decidePick(
    id: string, decision: 'approve' | 'skip', reason: string | null, characterSlug: string | null, extras: DecideExtras = {},
  ) {
    const note = extras.ownerNote?.trim() || null;
    const mode = extras.ownerMode?.trim() || null;
    const presence = extras.ownerPresence?.trim() || null;
    const music = extras.ownerMusic?.trim() || null;
    const props = (extras.ownerProps ?? []).map((x) => x.trim());
    const also = extras.alsoCharacter?.trim() || null;
    if (decision !== 'approve' && decision !== 'skip') throw new DemoError(`decision must be approve or skip, got ${decision}`);
    if (note && note.length > 280) throw new DemoError(`the note is limited to 280 characters, got ${note.length}`);
    if (mode && mode !== 'dropin' && mode !== 'recreate') throw new DemoError(`owner_mode must be dropin or recreate, got ${mode}`);
    if (presence && !['cameo', 'featured', 'star'].includes(presence)) {
      throw new DemoError(`owner_presence must be cameo, featured or star, got ${presence}`);
    }
    if (music && !MUSIC_ARMS.includes(music)) throw new DemoError(`owner_music must be in_app, original or ai_beat, got ${music}`);
    if (props.length > PROPS_MAX) throw new DemoError(`owner_props takes at most ${PROPS_MAX} items, got ${props.length}`);
    if (props.some((x) => x.length < 1 || x.length > PROP_MAX_CHARS)) throw new DemoError(`each of owner_props must be 1 to ${PROP_MAX_CHARS} characters`);
    if (also && decision !== 'approve') throw new DemoError('also_character only applies when approving');
    const f = this.favs.find((x) => x.id === id);
    if (!f) throw new DemoError(`unknown pick ${id}`);
    if (f.status === 'queued' || f.status === 'made') throw new DemoError(`pick ${id} is already ${f.status}: too late to decide`);
    if (music === 'original' && (mode ?? (f.proposal.owner_mode as string | undefined)) === 'recreate') {
      throw new DemoError('owner_music original needs the dropin mode: a Recreate has no original audio (use ai_beat or in_app)');
    }
    const slug = characterSlug?.trim() || f.character_slug;
    if (slug && !(slug in NAMES)) throw new DemoError(`unknown character ${slug}`);
    if (decision === 'approve' && !slug) throw new DemoError('choose a character before approving this pick');
    if (also) {
      if (!(also in NAMES)) throw new DemoError(`unknown character ${also}`);
      if (also === slug) throw new DemoError(`also_character must be a different character from ${slug}`);
    }

    const owner: Record<string, unknown> = {};
    if (decision === 'approve') {
      if (note) owner.owner_note = note;
      if (mode) owner.owner_mode = mode;
      if (presence && (mode ?? (f.proposal.owner_mode as string | undefined)) === 'dropin') owner.owner_presence = presence;
      if (props.length) owner.owner_props = props;
      if (music) owner.owner_music = music;
    }
    const record = { decision, by: 'owner', reason: reason?.trim() || null, at: new Date(this.now()).toISOString() }; // 0011: when the owner decided
    const { hold_reason: _drop, ...rest } = f.proposal;
    void _drop;
    f.proposal = { ...rest, ...owner, decision: record };
    f.character_slug = slug;
    f.status = decision === 'skip' ? 'skipped' : f.status === 'analysed' || f.status === 'approved' ? f.status : 'approved';

    if (also) {
      const sib = this.favs.find((x) => x.url === f.url && x.character_slug === also && x.id !== f.id);
      if (sib) {
        if (sib.status !== 'queued' && sib.status !== 'made') {
          const { hold_reason: _h, ...sibRest } = sib.proposal;
          void _h;
          sib.proposal = { ...sibRest, ...owner, decision: record };
          if (sib.status !== 'approved' && sib.status !== 'analysed') sib.status = 'approved';
        }
      } else {
        this.favs.push({
          id: uid('fs'), url: f.url, platform: f.platform, creator_handle: f.creator_handle, views: f.views, outlier_x: f.outlier_x,
          origin: f.origin, character_slug: also, proposal: { ...f.proposal }, scores: { ...f.scores }, total_score: f.total_score,
          note: null, status: 'approved', created_at: new Date(this.now()).toISOString(), clip_id: null,
        });
      }
    }
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

  /** attach_clip of migration 0008 (the browser upload is simulated: the demo stores no media). */
  async attachClip(pickId: string, file: ClipFile, onProgress?: (pct: number) => void) {
    const f = this.favs.find((x) => x.id === pickId);
    if (!f) throw new DemoError(`unknown pick ${pickId}`);
    if (f.status === 'queued' || f.status === 'made') throw new DemoError(`pick ${pickId} is already ${f.status}: too late to attach a clip`);
    const checked = checkClipBasics(file);
    if (!checked.ok) throw new DemoError(checked.reason);
    for (const pct of [10, 45, 80, 100]) {
      onProgress?.(pct);
      await new Promise((r) => setTimeout(r, 40));
    }
    const path = ownerClipPath(pickId, file, this.now());
    f.proposal = { ...f.proposal, owner_clip_path: path };
    this.emit('favorites');
    return path;
  }

  /** add_drop of migration 0012: a file drop (then attachClip and requestJob process) or a pasted link. */
  async addDrop(characterSlug: string, link: string | null) {
    if (!(characterSlug in NAMES)) throw new DemoError(`unknown character ${characterSlug}`);
    const at = new Date(this.now()).toISOString();
    const decision = { decision: 'approve', by: 'owner', reason: "owner's own video", at };
    if (link == null) {
      const id = uid('fn');
      this.favs.push({
        id, url: `owner-drop:${id}`, platform: 'drop', creator_handle: null, views: null, outlier_x: null, origin: 'owner',
        character_slug: characterSlug, proposal: { decision, drop: { state: 'uploading', kind: 'file', at, reason: null, own_footage: false } }, scores: {},
        total_score: null, note: null, status: 'approved', created_at: at, clip_id: null,
      });
      this.emit('favorites');
      return { pickId: id, duplicate: false };
    }
    const { platform, url } = canonicalVideoUrl(link);
    const drop = { state: 'checking', kind: 'link', at, reason: null, own_footage: false };
    const existing = this.favs.find((f) => f.url === url && f.character_slug === characterSlug);
    if (existing) {
      if (existing.status !== 'queued' && existing.status !== 'made') {
        const { hold_reason: _h, ...rest } = existing.proposal;
        void _h;
        existing.proposal = { ...rest, decision, drop };
        existing.status = 'approved';
        this.emit('favorites');
      }
      return { pickId: existing.id, duplicate: true };
    }
    const id = uid('fl');
    const handle = platform === 'tiktok' ? `@${url.split('/@')[1].split('/')[0]}` : null;
    this.favs.push({
      id, url, platform, creator_handle: handle, views: null, outlier_x: null, origin: 'owner', character_slug: characterSlug,
      proposal: { decision, drop }, scores: {}, total_score: null, note: null, status: 'approved', created_at: at, clip_id: null,
    });
    this.emit('favorites');
    return { pickId: id, duplicate: false };
  }

  /** request_job of migration 0012 (the same refusals); the "cloud job" runs in tick() after 2 s. */
  async requestJob(pickId: string, kind: 'process' | 'make', adjust: DropAdjust | null = null) {
    if (kind !== 'process' && kind !== 'make') throw new DemoError(`kind must be process or make, got ${kind}`);
    const f = this.favs.find((x) => x.id === pickId);
    if (!f) throw new DemoError(`unknown pick ${pickId}`);
    const d = f.proposal.drop as Record<string, unknown> | undefined;
    if (!d || typeof d !== 'object') throw new DemoError(`pick ${pickId} is not a dropped video`);
    if (f.status === 'made') throw new DemoError(`pick ${pickId} is already made`);
    const at = new Date(this.now()).toISOString();
    const requested = { ...((d.requested as Record<string, string>) ?? {}), [kind]: at };
    if (kind === 'process') {
      if (!['uploading', 'checking', 'waiting', 'failed'].includes(String(d.state))) {
        throw new DemoError(`a check runs on an uploading, checking, waiting or failed drop; this one is ${d.state}`);
      }
      if (d.state === 'uploading' && !f.proposal.owner_clip_path) throw new DemoError('the upload has not finished: attach the video first');
      f.proposal = { ...f.proposal, drop: { ...d, state: 'checking', reason: null, at, requested } };
    } else {
      if (!['ready', 'failed'].includes(String(d.state)) || d.credits == null || !d.source_id) {
        throw new DemoError(`Make it needs a checked and priced drop (ready); this one is ${d.state}`);
      }
      if (adjust) {
        const ok = validateAdjust(adjust, d as unknown as DropCard);
        if (!ok.ok) throw new DemoError(ok.reason);
      }
      const { adjust: _a, ...rest } = d;
      void _a;
      f.proposal = {
        ...f.proposal, make_requested: { at, by: 'owner' },
        drop: { ...rest, state: 'making', reason: null, at, requested, ...(adjust && Object.keys(adjust).length ? { adjust } : {}) },
      };
    }
    this.emit('favorites');
    setTimeout(() => this.emit('favorites'), DEMO_JOB_MS + 100); // the board reloads when the demo's job is done
    return { dispatched: true };
  }

  /** set_drop_footage of migration 0012. */
  async setDropFootage(pickId: string, ownFootage: boolean) {
    if (typeof ownFootage !== 'boolean') throw new DemoError('own_footage must be true or false');
    const f = this.favs.find((x) => x.id === pickId);
    if (!f) throw new DemoError(`unknown pick ${pickId}`);
    const d = f.proposal.drop;
    if (!d || typeof d !== 'object') throw new DemoError(`pick ${pickId} is not a dropped video`);
    f.proposal = { ...f.proposal, drop: { ...(d as Record<string, unknown>), own_footage: ownFootage } };
    this.emit('favorites');
  }

  async previewUrl(path: string) {
    // the demo stores no media: a labelled stand-in strip of five frames
    const frames = Array.from({ length: 5 }, (_, i) =>
      `<rect x="${i * 36}" y="0" width="35" height="64" fill="hsl(${(path.length * 7 + i * 23) % 360} 45% ${28 + i * 4}%)"/>` +
      `<circle cx="${i * 36 + 17.5}" cy="26" r="8" fill="#fff" fill-opacity=".55"/>`).join('');
    const svg = `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 179 64">${frames}<text x="89" y="58" font-family="sans-serif" font-size="7" font-weight="700" fill="#fff" fill-opacity=".85" text-anchor="middle">DEMO SECTION</text></svg>`;
    return `data:image/svg+xml;utf8,${encodeURIComponent(svg)}`;
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
