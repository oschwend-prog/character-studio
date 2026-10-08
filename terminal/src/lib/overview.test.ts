// Terminal v3, "Studio at a glance" (spec section 5.1): one row per live character plus All, and the views per day by period.
// Pure functions over the snapshot (v_tracker, v_queue, v_library, v_channels, v_views_daily, the cadence in settings).
import { describe, expect, it } from 'vitest';
import { OVERVIEW_ALL, TEST_STATUS_LABEL, overviewRows, postsPerWeek, testStatusOf, viewsSeries } from './overview';
import type {
  Channel, Character, ClipState, DropCard, DropState, LibraryClip, LibraryPost, PostStatus, QueueClip, Snapshot, TrackerRow, ViewsDay,
} from './types';

// Thursday 8 October 2026, noon in London (BST)
const NOW = Date.parse('2026-10-08T12:00:00+01:00');
const HOUR = 3_600_000;
const DAY = 24 * HOUR;
const ago = (h: number) => new Date(NOW - h * HOUR).toISOString();
const inHours = (h: number) => new Date(NOW + h * HOUR).toISOString();

const card = (state: DropState, over: Partial<DropCard> = {}): DropCard => ({
  state, kind: 'file', at: ago(1), character_by: 'owner', window: { start_s: 0, length_s: 8 }, credits: 91, ...over,
});
let n = 0;
const row = (slug: string, drop: DropCard | null, over: Partial<TrackerRow> = {}): TrackerRow => {
  n += 1;
  return {
    pick_id: `pick-${n}`, character_slug: slug, character_name: slug, url: `owner-drop:${n}`, platform: 'drop',
    creator_handle: null, views: null, outlier_x: null, tier: null, theme: null, concept: null, hook: null, thumbnail_url: null,
    preview_url: null, gallery: false, posted_at: null, velocity: null, proposed_mode: null, owner_mode: null, owner_presence: null,
    owner_music: null, owner_clip_path: null, status: 'approved', decision: null, approved_at: ago(2), note: null, source_id: null,
    analysis: null, fetch_failed: null, clip_id: null, clip_state: null, clip_mode: null, clip_state_since: null, clip_failure: null,
    credits_spent: 0, post_id: null, post_status: null, post_scheduled_for: null, post_posted_at: null, post_url: null, post_error: null,
    latest_views: null, caption: null, hashtags: null, first_comment: null, drop_card: drop, make_requested_at: null,
    ...over,
  };
};
const times = <T>(count: number, make: () => T): T[] => Array.from({ length: count }, make);

const character = (slug: string, name: string, status: string): Character => ({ slug, name, status, bodies: ['biped'], setup: {}, accounts: [] });
const channel = (slug: string, platform: 'instagram' | 'tiktok', over: Partial<Channel> = {}): Channel => ({
  account_id: `${slug}-${platform}`, character_slug: slug, character_name: slug, character_status: 'live', platform, handle: `${slug}.${platform}`,
  connected: true, mode: 'approval', dropin_share: 1, dropin_ratio: 0, approved_posts: 0, autopilot_min_approved: 6, autopilot_unlocked: false,
  posts_posted: 0, posts_scheduled: 0, posts_problem: 0, views_7d: null, follows: null, median_outlier_x: null, hit_rate: null,
  measured_clips: 0, bar_status: null, next_slot: null, today_posts: [], ...over,
});
const post = (status: PostStatus, scheduledFor: string, views: number | null = null): LibraryPost => ({
  post_id: `post-${(n += 1)}`, platform: 'instagram', handle: null, status, scheduled_for: scheduledFor, url: null, views, likes: null,
  comments: null, shares: null, saves: null, captured_at: null,
});
const clip = (slug: string, state: ClipState, over: Partial<LibraryClip> = {}): LibraryClip => ({
  id: `clip-${(n += 1)}`, character_slug: slug, character_name: slug, mode: 'dropin', state, hook: `hook ${n}`, caption: null,
  master_path: `${slug}/m${n}.mp4`, reject_reason: null, created_at: ago(24 * 12), cost_credits: 91, outlier_x: null, format_id: null,
  posts: [], platforms: ['instagram'], views: null, posted_at: null, ...over,
});
const queued = (slug: string) => ({ id: `q-${(n += 1)}`, character_slug: slug }) as unknown as QueueClip;
const views = (slug: string, day: string, v: number, follows = 0): ViewsDay => ({ character_slug: slug, day, views: v, follows });

const snapshot = (over: Partial<Snapshot> = {}): Snapshot => ({
  channels: [], queue: [], library: [], budget: null, health: [], picks: [], history: [], characters: [], runs: [], tracker: [],
  viewsDaily: [], cadence: {}, loadedAt: NOW, ...over,
});

const CHARACTERS = [
  character('reginald', 'Reginald', 'live'), character('lenny', 'Lenny Gold', 'designing'), character('biscuit', 'Biscuit', 'paused'),
  character('franz', 'Franz', 'live'),
];

// Franz: today 100, yesterday not measured, a recount of -20 three days ago, 50 five days ago, 200 ten days ago, 1000 forty days ago
const VIEWS: ViewsDay[] = [
  views('franz', '2026-10-08', 100, 3), views('franz', '2026-10-06', -20, -1), views('franz', '2026-10-03', 50, 2),
  views('franz', '2026-09-28', 200, 5), views('franz', '2026-08-29', 1000, 10),
  views('franz', '2026-10-09', 999, 9), // a day still to come (a clock ahead): never counted
  views('reginald', '2026-10-08', 7), views('reginald', '2026-10-01', 40), // 7 days ago is outside "7 days" (today and the 6 before)
  views('lenny', '2026-10-08', 5000, 50), // not live: not on the board
];

function fixture(over: Partial<Snapshot> = {}): Snapshot {
  const franzBooked = clip('franz', 'scheduled', { posts: [post('scheduled', inHours(31))] });
  return snapshot({
    characters: CHARACTERS,
    tracker: [
      ...times(4, () => row('franz', card('ready'))), // Ready
      ...times(2, () => row('franz', card('ready', { character_by: 'studio' }))), // the studio chose him: still ready to make
      row('franz', card('making')),
      row('franz', card('ready'), { make_requested_at: ago(1) }), // Make it tapped, no clip yet: being made
      row('franz', card('blocked')), row('franz', card('checking')),
      row('franz', card('made'), { clip_id: 'c', clip_state: 'awaiting_approval' }),
      row('reginald', card('ready')),
      row('reginald', null, { clip_id: 'g', clip_state: 'generating', status: 'queued' }), // a scan pick being made
      ...times(3, () => row('lenny', card('ready'))),
    ],
    queue: [queued('franz'), queued('franz'), queued('reginald'), queued('lenny')],
    library: [
      clip('franz', 'posted', { posted_at: ago(48), views: 500, posts: [post('posted', ago(48), 500)] }),
      clip('franz', 'posted', { posted_at: ago(24 * 10), views: 5000 }), // the best ever, but not this week
      clip('franz', 'posted', { posted_at: ago(24 * 6), views: null }), // not measured yet
      franzBooked,
      clip('franz', 'approved'),
      clip('franz', 'scheduled', { posts: [post('scheduled', ago(3))] }), // late: not the next post
      clip('reginald', 'posted', { posted_at: ago(72), views: 900 }),
      clip('reginald', 'posted', { posted_at: ago(24), views: 900, id: 'reginald-newest' }),
      clip('reginald', 'awaiting_approval'),
      clip('lenny', 'posted', { posted_at: ago(5), views: 99_999 }),
    ],
    channels: [
      channel('franz', 'instagram', { bar_status: 'continue', hit_rate: 0.5, measured_clips: 2, next_slot: inHours(7) }),
      channel('franz', 'tiktok', { bar_status: 'kill', hit_rate: 0, measured_clips: 2, next_slot: inHours(7) }),
      channel('reginald', 'instagram', { next_slot: inHours(7.5) }),
      channel('reginald', 'tiktok', { connected: false, next_slot: inHours(1) }), // not connected: its slot is not his next post
      channel('lenny', 'instagram', { hit_rate: 1, measured_clips: 9, next_slot: inHours(0.5) }),
    ],
    viewsDaily: VIEWS,
    cadence: { franz: { days: ['tue', 'wed', 'thu'], slot: '19:00' }, lenny: { days: ['mon', 'tue', 'wed', 'thu', 'fri'], slot: '12:30' } },
    ...over,
  });
}

describe('overviewRows', () => {
  it('has one row per live character in the owner’s order, then All', () => {
    const rows = overviewRows(fixture(), NOW);
    expect(rows.map((r) => [r.slug, r.name])).toEqual([['franz', 'Franz'], ['reginald', 'Reginald'], [null, OVERVIEW_ALL]]);
  });

  it('counts his clips: ready to make (the Ready chip only), being made, to approve, scheduled, posted', () => {
    const [franz, reginald] = overviewRows(fixture(), NOW);
    expect(franz).toMatchObject({ readyToMake: 4, needsYou: 2, stock: 6, beingMade: 2, toApprove: 2, scheduled: 3, posted: 3 });
    expect(reginald).toMatchObject({ readyToMake: 1, needsYou: 0, stock: 1, beingMade: 1, toApprove: 1, scheduled: 0, posted: 2 });
  });

  it('counts the clips that wait for his character choice next to the ready ones ("4 ready +2 need your choice"), never inside', () => {
    const [franz, , all] = overviewRows(fixture(), NOW);
    expect([franz.readyToMake, franz.needsYou]).toEqual([4, 2]); // the studio chose him on 2 of his 6 checked clips
    expect(all.needsYou).toBe(2);
    const legacy = overviewRows(fixture({ tracker: [row('franz', card('ready', { character_by: undefined }))] }), NOW)[0];
    expect([legacy.readyToMake, legacy.needsYou, legacy.stock]).toEqual([0, 1, 1]); // a drop from before 0013: still his to confirm
  });

  it('works out the runway: his stock (ready + need your choice) ÷ his posts per week from the cadence, none without a cadence', () => {
    const [franz, reginald, all] = overviewRows(fixture(), NOW);
    expect([franz.postsPerWeek, franz.runwayWeeks]).toEqual([3, 2]); // 4 ready + 2 to choose, 3 posts a week
    expect([reginald.postsPerWeek, reginald.runwayWeeks]).toEqual([null, null]);
    expect(all.runwayWeeks).toBe(2); // only the characters with a cadence count
    const none = overviewRows(fixture({ cadence: {} }), NOW);
    expect(none.map((r) => r.runwayWeeks)).toEqual([null, null, null]);
    const thin = overviewRows(fixture({ cadence: { franz: { days: ['mon', 'tue', 'wed', 'thu'], slot: '19:00' } } }), NOW);
    expect(thin[0].runwayWeeks).toBe(1.5);
  });

  it('reads the posts per week like the slot functions: days lower-cased, 3 letters, each once, unknown ones ignored', () => {
    expect(postsPerWeek({ days: ['Tue', 'tuesday', ' WED ', 'xyz'], slot: '19:00' })).toBe(2);
    expect(postsPerWeek({ days: 'thu', slot: '19:00' })).toBe(1);
    for (const none of [undefined, null, {}, { days: [] }, { days: 42 }]) expect(postsPerWeek(none as never)).toBeNull();
  });

  it('adds up his views by London day: today, 7 days, 30 days, all time, a recount taken off and a day to come never', () => {
    const [franz, reginald] = overviewRows(fixture(), NOW);
    // v_views_daily telescopes: the -20 corrects an earlier overcount, so the totals are the sums as they are (what the posts show)
    expect(franz).toMatchObject({ viewsToday: 100, views7d: 130, views30d: 330, viewsAll: 1330, follows7d: 4, hasViews: true });
    expect(reginald).toMatchObject({ viewsToday: 7, views7d: 7, views30d: 47, viewsAll: 47, follows7d: 0, hasViews: true });
  });

  it('never shows a total below 0, nor a day below 0', () => {
    const recount = [views('franz', '2026-10-08', -30, -2), views('franz', '2026-10-07', 10, 1), views('franz', '2026-09-01', 100)];
    const [franz] = overviewRows(fixture({ viewsDaily: recount }), NOW);
    expect(franz).toMatchObject({ viewsToday: 0, views7d: 0, views30d: 0, viewsAll: 80, follows7d: 0 }); // -30 today; -20 over 7 days
  });

  it('takes "today" as the London day, not the UTC one', () => {
    const lateEvening = Date.parse('2026-10-08T23:30:00Z'); // 00:30 on Friday 9 October in London
    const [franz] = overviewRows(fixture(), lateEvening);
    expect(franz.viewsToday).toBe(999);
  });

  it('shows his next post: the soonest one booked, else his next slot with nothing booked', () => {
    const [franz, reginald, all] = overviewRows(fixture(), NOW);
    expect(franz.nextPost).toEqual({ at: inHours(31), booked: true });
    expect(reginald.nextPost).toEqual({ at: inHours(7.5), booked: false });
    expect(all.nextPost).toEqual({ at: inHours(31), booked: true }); // the studio's next real post
    const empty = overviewRows(snapshot({ characters: CHARACTERS }), NOW);
    expect(empty.map((r) => r.nextPost)).toEqual([null, null, null]);
  });

  it('gives his test status from his Instagram channel’s bar, his hit rate and his best video of the week', () => {
    const [franz, reginald, all] = overviewRows(fixture(), NOW);
    expect([franz.testStatus, reginald.testStatus, all.testStatus]).toEqual(['on_track', 'not_yet', null]);
    expect([franz.hitRate, reginald.hitRate, all.hitRate]).toEqual([0.25, null, 0.25]); // weighted by the clips measured
    expect(franz.bestThisWeek).toMatchObject({ views: 500, postedAt: ago(48), slug: 'franz' });
    expect(reginald.bestThisWeek?.clipId).toBe('reginald-newest'); // a tie: the newer one
    expect(all.bestThisWeek?.clipId).toBe('reginald-newest'); // the most viewed of the week across them
    const noInstagram = overviewRows(fixture({ channels: [channel('franz', 'tiktok', { bar_status: 'promote' })] }), NOW);
    expect(noInstagram[0].testStatus).toBeNull();
  });

  it('takes "this week" as the last 7 London days, not the last 7 x 24 hours', () => {
    const library = [
      clip('franz', 'posted', { id: 'thu-evening', posted_at: '2026-10-01T19:00:00+01:00', views: 9000 }), // 6 days 17 h ago: last week's Thursday
      clip('franz', 'posted', { id: 'fri-night', posted_at: '2026-10-02T00:30:00+01:00', views: 800 }), // the first of the 7 days
      clip('franz', 'posted', { id: 'later-today', posted_at: inHours(5), views: 99_999 }), // a time still to come: never
    ];
    const [franz] = overviewRows(fixture({ library }), NOW);
    expect(franz.bestThisWeek?.clipId).toBe('fri-night');
  });

  it('names the test status in plain words', () => {
    expect(['continue', 'promote', 'kill', 'not_yet', null, 'weird'].map((b) => testStatusOf(b))).toEqual([
      'on_track', 'promote', 'at_risk', 'not_yet', 'not_yet', 'not_yet',
    ]);
    expect(TEST_STATUS_LABEL).toEqual({ not_yet: 'Not yet', on_track: 'On track', promote: 'Promote', at_risk: 'At risk' });
  });

  it('sums the live characters in the All row', () => {
    const rows = overviewRows(fixture(), NOW);
    const all = rows.at(-1)!;
    const live = rows.slice(0, -1);
    for (const key of ['readyToMake', 'needsYou', 'stock', 'beingMade', 'toApprove', 'scheduled', 'posted', 'viewsToday', 'views7d', 'views30d', 'viewsAll', 'follows7d'] as const) {
      expect([key, all[key]]).toEqual([key, live.reduce((s, r) => s + r[key], 0)]);
    }
    expect(all).toMatchObject({ readyToMake: 5, needsYou: 2, stock: 7, toApprove: 3, viewsToday: 107, viewsAll: 1377, hasViews: true });
  });

  it('shows zeros and hasViews false before anything is measured', () => {
    const rows = overviewRows(fixture({ viewsDaily: [] }), NOW);
    for (const r of rows) {
      expect(r).toMatchObject({ viewsToday: 0, views7d: 0, views30d: 0, viewsAll: 0, follows7d: 0, hasViews: false });
    }
    const empty = overviewRows(snapshot(), NOW);
    expect(empty).toHaveLength(1); // no character live yet: only All, all zeros
    expect(empty[0]).toMatchObject({ slug: null, readyToMake: 0, needsYou: 0, stock: 0, viewsAll: 0, hasViews: false, runwayWeeks: null, hitRate: null, bestThisWeek: null });
  });
});

describe('viewsSeries', () => {
  const dayAfter = (key: string) => new Date(Date.parse(`${key}T12:00:00Z`) + DAY).toISOString().slice(0, 10);

  it('fills every day of the last 7 London days per character, a gap as 0 and a recount day drawn at 0 (the chart only)', () => {
    const s = viewsSeries(VIEWS, '7d', NOW);
    expect(s.days).toEqual(['2026-10-02', '2026-10-03', '2026-10-04', '2026-10-05', '2026-10-06', '2026-10-07', '2026-10-08']);
    expect(s.lines.map((l) => l.slug)).toEqual(['franz', 'reginald', 'lenny']); // the owner's order
    expect(s.lines[0].views).toEqual([0, 50, 0, 0, 0, 0, 100]);
    expect(s.lines[1].views).toEqual([0, 0, 0, 0, 0, 0, 7]);
    expect(s.hasViews).toBe(true);
  });

  it('covers 30 days or all time, from the first day measured', () => {
    const month = viewsSeries(VIEWS, '30d', NOW);
    expect([month.days.length, month.days[0], month.days.at(-1)]).toEqual([30, '2026-09-09', '2026-10-08']);
    expect(month.lines[0].views.reduce((a, b) => a + b, 0)).toBe(350);
    const all = viewsSeries(VIEWS, 'all', NOW);
    expect([all.days[0], all.days.at(-1), all.days.length]).toEqual(['2026-08-29', '2026-10-08', 41]);
    expect(all.lines[0].views.reduce((a, b) => a + b, 0)).toBe(1350);
  });

  it('keeps to the characters asked for, in that order, a character with no views as zeros', () => {
    const s = viewsSeries(VIEWS, '7d', NOW, ['reginald', 'franz', 'borat']);
    expect(s.lines.map((l) => [l.slug, l.views.reduce((a, b) => a + b, 0)])).toEqual([['reginald', 7], ['franz', 150], ['borat', 0]]);
    expect(viewsSeries(VIEWS, '7d', NOW, ['borat']).hasViews).toBe(false);
  });

  it('has zero days and hasViews false before anything is measured', () => {
    const week = viewsSeries([], '7d', NOW);
    expect([week.days.length, week.lines, week.hasViews]).toEqual([7, [], false]);
    expect(viewsSeries([], 'all', NOW).days).toEqual(['2026-10-08']);
    expect(viewsSeries([], '30d', NOW, ['franz']).lines).toEqual([{ slug: 'franz', views: Array(30).fill(0) }]);
  });

  it('counts calendar days across the clock change', () => {
    const s = viewsSeries([], '30d', Date.parse('2026-11-05T12:00:00Z')); // the clocks went back on 25 October
    expect([s.days[0], s.days.at(-1)]).toEqual(['2026-10-07', '2026-11-05']);
    expect(new Set(s.days).size).toBe(30);
    for (let i = 1; i < s.days.length; i += 1) expect(s.days[i]).toBe(dayAfter(s.days[i - 1]));
  });
});

describe('the demo', () => {
  it('has a row with views for every live character it posts for, 30 days of views and a clip waiting for approval', async () => {
    const { DemoBackend } = await import('../demo/backend');
    const snap = await new DemoBackend(() => NOW).load();
    const rows = overviewRows(snap, NOW);
    expect(rows.length).toBeGreaterThanOrEqual(3);
    expect(rows.at(-1)!.toApprove).toBeGreaterThan(0);
    expect(rows.some((r) => r.slug && r.hasViews && r.viewsAll > 0 && r.runwayWeeks != null && r.bestThisWeek)).toBe(true);
    expect(rows.some((r) => r.slug && !r.hasViews)).toBe(true); // one has not posted yet: the empty cells show too
    const month = viewsSeries(snap.viewsDaily, '30d', NOW, rows.filter((r) => r.slug).map((r) => r.slug!));
    const daysWithViews = month.days.filter((_, i) => month.lines.some((l) => l.views[i] > 0));
    expect(daysWithViews.length).toBeGreaterThanOrEqual(25);
    // the views per day add up to what the library's posts show, and so does the total on the board
    for (const slug of ['reginald', 'lenny']) {
      const library = snap.library.filter((c) => c.character_slug === slug).reduce((s, c) => s + (c.views ?? 0), 0);
      expect(snap.viewsDaily.filter((d) => d.character_slug === slug).reduce((s, d) => s + d.views, 0)).toBe(library);
      expect(rows.find((r) => r.slug === slug)!.viewsAll).toBe(library);
    }
    expect(Object.keys(snap.cadence).length).toBeGreaterThan(0);
  });
});
