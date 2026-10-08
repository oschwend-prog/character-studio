// Terminal v2, Today page: the counts of "what needs you" and a character's last posts. Pure functions over the snapshot.
import { describe, expect, it } from 'vitest';
import {
  creditsLeft, hasWarnings, lastPosts, liveChannels, liveLastPosts, postNumbers, problemClips, problemClipsLine, todayCounts, warningCount,
} from './dashboard';
import { dropCredits } from './drop';
import type { Character, ClipState, HealthRow, DropAdjust, DropCard, DropState, LibraryClip, LibraryPost, QueueClip, Snapshot, TrackerRow } from './types';

const NOW = Date.parse('2026-10-07T12:00:00Z');
const HOUR = 3_600_000;
const ago = (h: number) => new Date(NOW - h * HOUR).toISOString();

const card = (state: DropState, over: Partial<DropCard> = {}): DropCard => ({ state, kind: 'file', at: ago(1), ...over });

let n = 0;
const row = (drop: DropCard | null, over: Partial<TrackerRow> = {}): TrackerRow => {
  n += 1;
  return {
    pick_id: `pick-${String(n).padStart(3, '0')}`, character_slug: 'reginald', character_name: 'Reginald', url: `owner-drop:${n}`, platform: 'drop',
    creator_handle: null, views: null, outlier_x: null, tier: null, theme: null, concept: null, hook: null, thumbnail_url: null,
    preview_url: null, gallery: false, posted_at: null, velocity: null, proposed_mode: null, owner_mode: null, owner_presence: null,
    owner_music: null, owner_clip_path: null, status: 'approved', decision: { decision: 'approve', by: 'owner', reason: "owner's own video" },
    approved_at: ago(2), note: null, source_id: null, analysis: null, fetch_failed: null, clip_id: null, clip_state: null, clip_mode: null,
    clip_state_since: null, clip_failure: null, credits_spent: 0, post_id: null, post_status: null, post_scheduled_for: null,
    post_posted_at: null, post_url: null, post_error: null, latest_views: null, caption: null, hashtags: null, first_comment: null,
    drop_card: drop, make_requested_at: null,
    ...over,
  };
};

const snapshot = (over: Partial<Snapshot> = {}): Snapshot => ({
  channels: [], queue: [], library: [], budget: null, health: [], picks: [], history: [], characters: [], runs: [], tracker: [], viewsDaily: [], cadence: {}, hits: [], loadedAt: NOW,
  ...over,
});
const queued = (count: number) => Array.from({ length: count }, (_, i) => ({ id: `q${i}` }) as unknown as QueueClip);

describe('todayCounts', () => {
  // 9 s of the clip's own sound: ceil(9 x 11) + 3 = 102; 8 s: 91; 12 s: 135
  const WINDOW_8 = { start_s: 0, length_s: 8 };
  const READY_8 = card('ready', { character_by: 'owner', window: WINDOW_8 });

  it('counts the clips that wait for a character, the ready ones with their price, those being made and the queue', () => {
    const data = snapshot({
      tracker: [
        row(card('ready', { character_by: 'studio', window: WINDOW_8 })), // pick a character: not priced (the character may change)
        row(card('checking', { character_by: 'studio' })),
        row(card('ready', { character_by: 'studio', window: { start_s: 0, length_s: 12 } })),
        row(READY_8),
        row(card('making')),
        row(card('made'), { clip_id: 'c1', clip_state: 'awaiting_approval' }),
        row(null), // a scan pick has no card: not counted
      ],
      queue: queued(3),
    });
    expect(dropCredits(READY_8)).toBe(91);
    expect(todayCounts(data)).toEqual({ needCharacter: 2, ready: 1, readyCredits: 91, making: 1, toApprove: 3 });
  });

  it('prices every ready clip with its own Adjust, like the drops table', () => {
    const adjust: DropAdjust = { length_s: 12 };
    const data = snapshot({
      tracker: [row(READY_8), row({ ...READY_8, adjust })],
    });
    expect(todayCounts(data)).toMatchObject({ ready: 2, readyCredits: 91 + dropCredits(READY_8, adjust) });
  });

  it('is all zero on an empty snapshot', () => {
    expect(todayCounts(snapshot())).toEqual({ needCharacter: 0, ready: 0, readyCredits: 0, making: 0, toApprove: 0 });
  });

  it('counts a clip being generated as making, and ignores blocked, failed and done clips', () => {
    const data = snapshot({
      tracker: [
        row(card('making'), { clip_id: 'c2', clip_state: 'generating' }),
        row(card('blocked')),
        row(card('failed')),
        row(card('made'), { clip_id: 'c3', clip_state: 'posted' }),
      ],
    });
    expect(todayCounts(data)).toEqual({ needCharacter: 0, ready: 0, readyCredits: 0, making: 1, toApprove: 0 });
  });
});

let m = 0;
const post = (over: Partial<LibraryPost> = {}): LibraryPost => ({
  post_id: `post-${++m}`, platform: 'tiktok', handle: '@reginald', status: 'posted', scheduled_for: ago(30), url: null, views: null, likes: null,
  comments: null, shares: null, saves: null, captured_at: null, ...over,
});
let k = 0;
const clip = (state: ClipState, over: Partial<LibraryClip> = {}): LibraryClip => ({
  id: `clip-${++k}`, character_slug: 'reginald', character_name: 'Reginald', mode: 'dropin', state, hook: `hook ${k}`, caption: null,
  master_path: null, reject_reason: null, created_at: ago(100), cost_credits: 91, outlier_x: null, format_id: null, posts: [], platforms: [],
  views: null, posted_at: null, ...over,
});

describe('lastPosts', () => {
  const library = [
    clip('posted', { id: 'old', hook: 'old one', posted_at: ago(72), posts: [post({ views: 100, likes: 10, shares: 1 })] }),
    clip('posted', {
      id: 'new', hook: 'new one', posted_at: ago(2),
      posts: [post({ views: 1_000, likes: 80, shares: 7 }), post({ platform: 'instagram', views: 500, likes: 20, shares: 3 })],
    }),
    clip('posted', { id: 'mid', hook: null, posted_at: ago(24), posts: [post({ views: 300, likes: null, shares: 2 })] }),
    clip('posted', { id: 'franz', character_slug: 'franz', posted_at: ago(1), posts: [post({ views: 9_999 })] }),
    clip('scheduled', { id: 'later', posted_at: null, posts: [post({ status: 'scheduled' })] }),
    clip('awaiting_approval', { id: 'waiting' }),
    clip('posted', { id: 'fresh', hook: 'fresh one', posted_at: ago(0.5), posts: [post({ views: null, likes: null, shares: null })] }),
  ];

  it('lists the posted clips of that character, newest first, with the sums over their posts', () => {
    expect(lastPosts(library, 'reginald')).toEqual([
      { clipId: 'fresh', hook: 'fresh one', postedAt: ago(0.5), views: null, likes: null, shares: null },
      { clipId: 'new', hook: 'new one', postedAt: ago(2), views: 1_500, likes: 100, shares: 10 },
      { clipId: 'mid', hook: null, postedAt: ago(24), views: 300, likes: null, shares: 2 },
    ]);
  });

  it('says "no numbers yet" (null), never 0, for a clip no post of which has metrics; a real 0 stays 0', () => {
    const lib = [
      clip('posted', { id: 'none', posted_at: ago(1), posts: [post(), post({ platform: 'instagram' })] }),
      clip('posted', { id: 'no-posts', posted_at: ago(2), posts: [] }),
      clip('posted', { id: 'zero', posted_at: ago(3), posts: [post({ views: 0, likes: 0, shares: 0, captured_at: ago(1) })] }),
      clip('posted', { id: 'one-read', posted_at: ago(4), posts: [post(), post({ platform: 'instagram', views: 40, likes: 4, shares: 1, captured_at: ago(1) })] }),
    ];
    const byId = Object.fromEntries(lastPosts(lib, 'reginald', 10).map((p) => [p.clipId, p]));
    expect(byId.none).toMatchObject({ views: null, likes: null, shares: null });
    expect(byId['no-posts']).toMatchObject({ views: null, likes: null, shares: null });
    expect(byId.zero).toMatchObject({ views: 0, likes: 0, shares: 0 });
    expect(byId['one-read']).toMatchObject({ views: 40, likes: 4, shares: 1 });
  });

  it('takes the n newest (3 by default) and never other characters, scheduled or unposted clips', () => {
    expect(lastPosts(library, 'reginald', 10).map((p) => p.clipId)).toEqual(['fresh', 'new', 'mid', 'old']);
    expect(lastPosts(library, 'reginald', 1).map((p) => p.clipId)).toEqual(['fresh']);
    expect(lastPosts(library, 'franz').map((p) => p.clipId)).toEqual(['franz']);
    expect(lastPosts(library, 'lenny')).toEqual([]);
    expect(lastPosts([], 'reginald')).toEqual([]);
  });

  it('falls back to the clip’s creation time when it has no posted time', () => {
    const lib = [
      clip('posted', { id: 'a', created_at: ago(10), posted_at: null }),
      clip('posted', { id: 'b', created_at: ago(5), posted_at: null }),
    ];
    expect(lastPosts(lib, 'reginald').map((p) => p.clipId)).toEqual(['b', 'a']);
  });
});

describe('postNumbers', () => {
  it('writes views, likes and shares on one line, in short form', () => {
    expect(postNumbers({ views: 1_500, likes: 100, shares: 10 })).toBe('1.5K views · 100 likes · 10 shares');
  });

  it('shows a dash for a number nobody has read yet and keeps a real 0', () => {
    expect(postNumbers({ views: 300, likes: null, shares: 2 })).toBe('300 views · — likes · 2 shares');
    expect(postNumbers({ views: 0, likes: 0, shares: 0 })).toBe('0 views · 0 likes · 0 shares');
  });

  it('says "no numbers yet" when none of the three has been read, never 0', () => {
    expect(postNumbers({ views: null, likes: null, shares: null })).toBe('no numbers yet');
  });
});

describe('liveLastPosts', () => {
  const character = (slug: string, name: string, status: string): Character => ({ slug, name, status, bodies: [], setup: {}, accounts: [] }) as unknown as Character;
  const characters = [
    character('lenny', 'Lenny Gold', 'live'),
    character('biscuit', 'Biscuit', 'paused'),
    character('franz', 'Franz', 'designing'),
    character('reginald', 'Reginald', 'live'),
  ];
  const library = [
    clip('posted', { id: 'r1', posted_at: ago(2), posts: [post({ views: 10 })] }),
    clip('posted', { id: 'f1', character_slug: 'franz', posted_at: ago(1) }),
    clip('posted', { id: 'b1', character_slug: 'biscuit', posted_at: ago(1) }),
  ];

  it('has one entry per live character in the owner’s order, with his last posts; characters not live are left out', () => {
    const out = liveLastPosts({ characters, library });
    expect(out.map((c) => [c.slug, c.name, c.posts.map((p) => p.clipId)])).toEqual([
      ['reginald', 'Reginald', ['r1']],
      ['lenny', 'Lenny Gold', []],
    ]);
  });

  it('is empty while no character is live or loaded, and passes n on', () => {
    expect(liveLastPosts({ characters: [], library })).toEqual([]);
    const many = [1, 2, 3, 4].map((i) => clip('posted', { id: `m${i}`, posted_at: ago(i) }));
    expect(liveLastPosts({ characters: [character('reginald', 'Reginald', 'live')], library: many }, 2)[0].posts).toHaveLength(2);
  });
});

describe('creditsLeft', () => {
  it('is the cap minus what is committed, never below 0', () => {
    expect(creditsLeft({ cap: 6_000, committed: 1_250 })).toBe(4_750);
    expect(creditsLeft({ cap: 6_000, committed: 6_000 })).toBe(0);
    expect(creditsLeft({ cap: 6_000, committed: 6_400 })).toBe(0);
  });

  it('is null while the budget has not loaded', () => {
    expect(creditsLeft(null)).toBeNull();
    expect(creditsLeft(undefined)).toBeNull();
  });
});

describe('liveChannels', () => {
  const ch = (slug: string, character_status: string, platform: string) => ({ account_id: `${slug}-${platform}`, character_slug: slug, character_status, platform });

  it('keeps only the channels of a live character (Tonight is per live character)', () => {
    const channels = [
      ch('reginald', 'live', 'tiktok'),
      ch('reginald', 'live', 'instagram'),
      ch('franz', 'designing', 'tiktok'),
      ch('biscuit', 'paused', 'instagram'),
      ch('lenny', 'retired', 'tiktok'),
    ];
    expect(liveChannels(channels).map((c) => c.account_id)).toEqual(['reginald-tiktok', 'reginald-instagram']);
    expect(liveChannels([ch('franz', 'designing', 'tiktok')])).toEqual([]);
    expect(liveChannels([])).toEqual([]);
  });
});

describe('problemClips, problemClipsLine and hasWarnings', () => {
  const blocked = row(card('blocked'));
  const failed = row(card('failed'), { clip_id: 'c9', clip_state: 'gen_failed' });
  const fine = [row(card('ready', { character_by: 'owner', window: { start_s: 0, length_s: 8 } })), row(card('making')), row(card('made'), { clip_id: 'c8', clip_state: 'posted' }), row(card('checking')), row(null)];
  const warn: HealthRow = { kind: 'post', severity: 'warning', message: 'post on x failed', ref_id: 'p1', since: ago(1) };

  it('counts the dropped clips that are blocked or failed, and nothing else', () => {
    expect(problemClips(snapshot({ tracker: [blocked, failed, ...fine] }))).toBe(2);
    expect(problemClips(snapshot({ tracker: fine }))).toBe(0);
    expect(problemClips(snapshot())).toBe(0);
  });

  it('words the warning row in the singular and the plural', () => {
    expect(problemClipsLine(1)).toBe('1 clip is blocked or failed');
    expect(problemClipsLine(3)).toBe('3 clips are blocked or failed');
  });

  it('shows the warnings when v_health has a row or a drop is blocked or failed, and stays quiet otherwise', () => {
    expect(hasWarnings(snapshot({ tracker: fine }))).toBe(false);
    expect(hasWarnings(snapshot({ health: [warn], tracker: fine }))).toBe(true);
    expect(hasWarnings(snapshot({ tracker: [blocked] }))).toBe(true);
    expect(hasWarnings(snapshot({ tracker: [failed] }))).toBe(true);
    expect(hasWarnings(snapshot({ health: [warn], tracker: [failed] }))).toBe(true);
  });

  it('counts the Today tab’s badge like the warnings Today shows: the v_health rows and the blocked or failed clips', () => {
    expect(warningCount(snapshot({ tracker: fine }))).toBe(0);
    expect(warningCount(snapshot({ health: [warn], tracker: fine }))).toBe(1);
    expect(warningCount(snapshot({ tracker: [blocked, failed, ...fine] }))).toBe(2);
    expect(warningCount(snapshot({ health: [warn, warn], tracker: [blocked, failed, ...fine] }))).toBe(4);
    expect((warningCount(snapshot({ health: [warn], tracker: [failed] })) > 0)).toBe(hasWarnings(snapshot({ health: [warn], tracker: [failed] })));
  });
});
