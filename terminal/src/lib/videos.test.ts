// Terminal v2, Videos page: what is being made and what is scheduled. Pure functions over the snapshot.
import { describe, expect, it } from 'vitest';
import { artistGroups, artistVideos } from './artist';
import { clipPlatforms, isTrackerRow, slotTime, videoGroups } from './videos';
import type { ClipState, DropCard, DropState, LibraryClip, LibraryPost, Snapshot, TrackerRow } from './types';

const NOW = Date.parse('2026-10-07T12:00:00Z');
const HOUR = 3_600_000;
const ago = (h: number) => new Date(NOW - h * HOUR).toISOString();
const ahead = (h: number) => new Date(NOW + h * HOUR).toISOString();

const card = (state: DropState, over: Partial<DropCard> = {}): DropCard => ({ state, kind: 'file', at: ago(1), ...over });

let n = 0;
const row = (drop: DropCard | null, over: Partial<TrackerRow> = {}): TrackerRow => {
  n += 1;
  return {
    pick_id: `pick-${String(n).padStart(3, '0')}`, character_slug: 'reginald', character_name: 'Reginald', url: `owner-drop:${n}`, platform: 'drop',
    creator_handle: null, views: null, outlier_x: null, tier: null, theme: null, concept: null, hook: null, thumbnail_url: null,
    preview_url: null, gallery: false, posted_at: null, velocity: null, proposed_mode: null, owner_mode: null, owner_presence: null,
    owner_music: null, owner_clip_path: null, status: 'queued', decision: { decision: 'approve', by: 'owner', reason: "owner's own video" },
    approved_at: ago(2), note: null, source_id: null, analysis: null, fetch_failed: null, clip_id: null, clip_state: null, clip_mode: null,
    clip_state_since: null, clip_failure: null, credits_spent: 0, post_id: null, post_status: null, post_scheduled_for: null,
    post_posted_at: null, post_url: null, post_error: null, latest_views: null, caption: null, hashtags: null, first_comment: null,
    drop_card: drop, make_requested_at: null,
    ...over,
  };
};

let m = 0;
const post = (scheduled_for: string, over: Partial<LibraryPost> = {}): LibraryPost => ({
  post_id: `post-${++m}`, platform: 'tiktok', handle: '@reginald', status: 'scheduled', scheduled_for, url: null, views: null, likes: null,
  comments: null, shares: null, saves: null, captured_at: null, ...over,
});
const clip = (id: string, state: ClipState, over: Partial<LibraryClip> = {}): LibraryClip => ({
  id, character_slug: 'reginald', character_name: 'Reginald', mode: 'dropin', state, hook: `hook ${id}`, caption: null, master_path: null,
  reject_reason: null, created_at: ago(5), cost_credits: 91, outlier_x: null, format_id: null, posts: [], platforms: [], views: null,
  posted_at: null, ...over,
});
const snapshot = (over: Partial<Snapshot> = {}): Snapshot => ({
  channels: [], queue: [], library: [], budget: null, health: [], picks: [], history: [], characters: [], runs: [], tracker: [], loadedAt: NOW,
  ...over,
});

describe('videoGroups: making', () => {
  it('lists the tracker rows being made, then the library clips in production that no row already shows', () => {
    const making = row(card('making'), { clip_id: 'c1', clip_state: 'generating' });
    const requested = row(card('ready', { character_by: 'owner' }), { make_requested_at: ago(0.2) }); // tapped, no clip yet
    const data = snapshot({
      tracker: [
        making,
        requested,
        row(card('ready', { character_by: 'owner' })), // ready, not made yet
        row(card('made'), { clip_id: 'c4', clip_state: 'awaiting_approval' }),
        row(card('failed')),
      ],
      library: [
        clip('c1', 'generating'), // already listed through its row
        clip('c2', 'planned', { created_at: ago(4) }),
        clip('c3', 'qa_passed', { created_at: ago(1) }),
        clip('c4', 'awaiting_approval'),
        clip('c5', 'posted'),
        clip('c6', 'dropped'),
      ],
    });
    const g = videoGroups(data);
    expect(g.making.map((x) => (isTrackerRow(x) ? x.pick_id : x.id))).toEqual([making.pick_id, requested.pick_id, 'c3', 'c2']);
    expect(g.making.filter((x): x is LibraryClip => !isTrackerRow(x)).map((x) => x.id)).toEqual(['c3', 'c2']); // newest library clip first
  });

  it('never lists one clip twice: a library clip whose row is making is only the row', () => {
    const a = row(card('making'), { clip_id: 'c1', clip_state: 'planned' });
    const b = row(card('making'), { clip_id: 'c2', clip_state: 'mastered' });
    const g = videoGroups(snapshot({ tracker: [a, b], library: [clip('c1', 'planned'), clip('c2', 'mastered')] }));
    expect(g.making).toEqual([a, b]);
    const clipIds = g.making.map((x) => (isTrackerRow(x) ? x.clip_id : x.id));
    expect(new Set(clipIds).size).toBe(clipIds.length);
  });

  it('does not list the half-made clip of a failed drop: its row shows it Failed on the Clips page', () => {
    const failed = row(card('failed'), { clip_id: 'c1', clip_state: 'gen_failed', clip_failure: 'Higgsfield refused the job' });
    const blocked = row(card('blocked'), { clip_id: 'c2', clip_state: 'qa_failed' });
    const done = row(card('made'), { clip_id: 'c3', clip_state: 'rejected', status: 'made' });
    const g = videoGroups(snapshot({
      tracker: [failed, blocked, done],
      library: [clip('c1', 'gen_failed'), clip('c2', 'qa_failed'), clip('c3', 'rejected'), clip('c9', 'gen_failed')],
    }));
    expect(g.making.map((x) => (isTrackerRow(x) ? x.pick_id : x.id))).toEqual(['c9']); // only a clip no row owns
  });

  it('is empty when nothing is being made', () => {
    expect(videoGroups(snapshot())).toEqual({ making: [], scheduled: [] });
  });
});

describe('videoGroups: scheduled', () => {
  it('lists the approved and scheduled library clips, the soonest slot first, clips without a slot last', () => {
    const later = clip('later', 'scheduled', { posts: [post(ahead(30))] });
    const soon = clip('soon', 'scheduled', { posts: [post(ahead(7)), post(ahead(7.5), { platform: 'instagram' })] });
    const approvedNoSlot = clip('approved-no-slot', 'approved');
    const approved = clip('approved', 'approved', { posts: [post(ahead(20))] });
    const data = snapshot({
      library: [
        later, approvedNoSlot, soon, approved,
        clip('posted', 'posted', { posts: [post(ago(3), { status: 'posted' })] }),
        clip('waiting', 'awaiting_approval'),
        clip('rejected', 'rejected'),
        clip('gen', 'generating'),
      ],
    });
    expect(videoGroups(data).scheduled.map((c) => c.id)).toEqual(['soon', 'approved', 'later', 'approved-no-slot']);
  });

  it('reads the live posts for the slot, so a failed earlier post does not move the clip up', () => {
    const c = clip('retry', 'scheduled', { posts: [post(ago(40), { status: 'failed' }), post(ahead(12))] });
    const other = clip('other', 'scheduled', { posts: [post(ahead(6))] });
    expect(videoGroups(snapshot({ library: [c, other] })).scheduled.map((x) => x.id)).toEqual(['other', 'retry']);
  });
});

describe('isTrackerRow', () => {
  it('tells a tracker row from a library clip', () => {
    expect(isTrackerRow(row(null))).toBe(true);
    expect(isTrackerRow(clip('c', 'planned'))).toBe(false);
  });
});

describe('slotTime', () => {
  it('is the first live slot (else the first post), null when no post has a time', () => {
    expect(slotTime(clip('a', 'scheduled', { posts: [post(ahead(9)), post(ahead(5), { platform: 'instagram' })] }))).toBe(ahead(5));
    expect(slotTime(clip('b', 'scheduled', { posts: [post(ago(40), { status: 'failed' }), post(ahead(12))] }))).toBe(ahead(12));
    expect(slotTime(clip('c', 'posted', { posts: [post(ago(3), { status: 'posted' }), post(ago(2), { status: 'posted' })] }))).toBe(ago(3));
    expect(slotTime(clip('d', 'approved'))).toBeNull();
    expect(slotTime(clip('e', 'approved', { posts: [post('not a time')] }))).toBeNull();
  });
});

describe('clipPlatforms', () => {
  it('is where the posts go, each platform once, else the clip’s own list', () => {
    expect(clipPlatforms(clip('a', 'scheduled', { posts: [post(ahead(5)), post(ahead(6), { platform: 'instagram' }), post(ahead(7))] }))).toEqual(['instagram', 'tiktok']);
    expect(clipPlatforms(clip('b', 'approved', { platforms: ['tiktok'] }))).toEqual(['tiktok']);
    expect(clipPlatforms(clip('c', 'approved'))).toEqual([]);
  });
});

describe("the artist page's three groups (artistVideos, artistGroups)", () => {
  it('lists Scheduled with the soonest slot first, where it goes and the clips without a slot last, other characters left out', () => {
    const data = snapshot({
      library: [
        clip('later', 'scheduled', { posts: [post(ahead(30))] }),
        clip('soon', 'scheduled', { posts: [post(ahead(7)), post(ahead(7.5), { platform: 'instagram' })] }),
        clip('no-slot', 'approved'),
        clip('franz-one', 'scheduled', { character_slug: 'franz', posts: [post(ahead(2))] }),
        clip('done', 'posted', { posts: [post(ago(3), { status: 'posted' })], posted_at: ago(3), views: 1200 }),
      ],
    });
    const v = artistVideos('reginald', data, NOW);
    expect(v.scheduled.map((x) => [x.id, x.where, x.at])).toEqual([
      ['soon', 'Scheduled', ahead(7)], ['later', 'Scheduled', ahead(30)], ['no-slot', 'Approved', null],
    ]);
    expect(v.scheduled[0].platforms).toEqual(['instagram', 'tiktok']);
    expect(v.scheduled.every((x) => x.route === 'library')).toBe(true);
    expect(v.stats).toMatchObject({ scheduled: 3, posted: 1, views: 1200 });
    expect(artistVideos('franz', data, NOW).scheduled.map((x) => x.id)).toEqual(['franz-one']);
  });

  it('lists a clip once: a tracker row whose clip waits for the OK, is scheduled or posted gives way to the clip', () => {
    const making = row(card('making'), { clip_id: 'c1', clip_state: 'generating' });
    const atOk = row(card('made'), { clip_id: 'c2', clip_state: 'awaiting_approval' });
    const booked = row(card('made'), { clip_id: 'c3', clip_state: 'scheduled', status: 'made' });
    const sent = row(null, { clip_id: 'c4', clip_state: 'posted', status: 'made', post_status: 'posted', post_posted_at: ago(5) });
    const ready = row(card('ready', { character_by: 'owner' }));
    const data = snapshot({
      tracker: [making, atOk, booked, sent, ready],
      queue: [{ id: 'c2', character_slug: 'reginald', hook: 'two' } as unknown as Snapshot['queue'][number]],
      library: [
        clip('c1', 'generating'), clip('c2', 'awaiting_approval'), clip('c3', 'scheduled', { posts: [post(ahead(3))] }),
        clip('c4', 'posted', { posted_at: ago(5), posts: [post(ago(5), { status: 'posted' })] }),
      ],
    });
    const v = artistVideos('reginald', data, NOW);
    expect(v.works.map((x) => x.id)).toEqual([making.pick_id, ready.pick_id]); // c2, c3 and c4 are listed by their own groups
    expect(v.queue.map((x) => x.id)).toEqual(['c2']);
    expect(v.scheduled.map((x) => x.id)).toEqual(['c3']);
    expect(v.posted.map((x) => x.id)).toEqual(['c4']);
    const ids = [...v.works, ...v.queue, ...v.scheduled, ...v.posted].map((x) => x.id);
    expect(ids).toHaveLength(5);
    expect(new Set(ids).size).toBe(5);
  });

  it('sends each row where it is: a making clip to Videos, a drop before Make it to Clips', () => {
    const making = row(card('making'), { clip_id: 'c1', clip_state: 'generating', concept: 'He spins' });
    const ready = row(card('ready', { character_by: 'owner' }));
    const checking = row(card('checking'));
    const v = artistVideos('reginald', snapshot({ tracker: [making, ready, checking], library: [clip('c1', 'generating')] }), NOW);
    expect(v.works.map((x) => [x.route, x.where])).toEqual([['making', 'Generating'], ['works', 'Ready'], ['works', 'Checking']]);
    expect(v.works[0].title).toBe('He spins');
    expect(v.works[1].title).toBe('Your video'); // never the internal owner-drop: key
  });

  it('groups them Live, Scheduled, In the making (his OK first, then the steps)', () => {
    const making = row(card('making'), { clip_id: 'c1', clip_state: 'generating' });
    const v = artistVideos('reginald', snapshot({
      tracker: [making],
      queue: [{ id: 'c2', character_slug: 'reginald', hook: 'two' } as unknown as Snapshot['queue'][number]],
      library: [clip('c1', 'generating'), clip('c2', 'awaiting_approval'), clip('c3', 'scheduled', { posts: [post(ahead(3))] }), clip('c4', 'posted', { posted_at: ago(5) })],
    }), NOW);
    const g = artistGroups(v);
    expect(g.making.map((x) => x.route)).toEqual(['queue', 'making']);
    expect(g.scheduled.map((x) => x.id)).toEqual(['c3']);
    expect(g.live.map((x) => x.id)).toEqual(['c4']);
    expect(artistGroups(artistVideos('nobody', snapshot(), NOW))).toEqual({ live: [], scheduled: [], making: [] });
  });
});
