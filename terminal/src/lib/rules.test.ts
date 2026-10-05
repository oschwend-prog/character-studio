import { describe, expect, it } from 'vitest';
import {
  AUTOPILOT_MIN_APPROVED,
  autopilotState,
  boardRows,
  canonicalVideoUrl,
  selectApprovable,
  sortPicks,
  spendState,
} from './rules';

describe('autopilot lock', () => {
  it('stays locked until the account has 6 approved posts', () => {
    expect(AUTOPILOT_MIN_APPROVED).toBe(6);
    const s = autopilotState({ mode: 'approval', approved_posts: 2 });
    expect(s).toMatchObject({ on: false, locked: true, remaining: 4, canToggle: false });
    expect(s.reason).toBe('Unlocks after 6 approved posts · 2 of 6 so far');
  });
  it('unlocks at exactly 6', () => {
    const s = autopilotState({ mode: 'approval', approved_posts: 6 });
    expect(s).toMatchObject({ on: false, locked: false, remaining: 0, canToggle: true });
  });
  it('can always be switched off, even when it was forced on below the bar', () => {
    const s = autopilotState({ mode: 'auto', approved_posts: 1 });
    expect(s).toMatchObject({ on: true, locked: true, canToggle: true });
  });
  it('treats a missing count as zero', () => {
    expect(autopilotState({ mode: 'approval', approved_posts: null }).remaining).toBe(6);
  });
});

const clip = (over: Partial<Parameters<typeof selectApprovable>[0][number]> = {}) => ({
  id: 'c1',
  state: 'awaiting_approval',
  master_path: 'c1/master.mp4',
  targets: [{ account_id: 'a1', platform: 'tiktok', handle: '@biscuit.moves' }],
  ...over,
});

describe('approve all: which clips the one tap approves', () => {
  it('takes every clip awaiting approval that has a master and somewhere to go', () => {
    const r = selectApprovable([clip({ id: 'a' }), clip({ id: 'b' })]);
    expect(r.ids).toEqual(['a', 'b']);
    expect(r.skipped).toEqual([]);
  });
  it('skips a clip without a master, one with no target account, and one in flight, saying why', () => {
    const r = selectApprovable(
      [
        clip({ id: 'ok' }),
        clip({ id: 'nomaster', master_path: null }),
        clip({ id: 'notarget', targets: [] }),
        clip({ id: 'busy' }),
        clip({ id: 'done', state: 'scheduled' }),
      ],
      new Set(['busy']),
    );
    expect(r.ids).toEqual(['ok']);
    expect(r.skipped).toEqual([
      { id: 'nomaster', reason: 'no master file yet' },
      { id: 'notarget', reason: 'no connected account can take it' },
    ]);
  });
});

describe('Viral Picks order', () => {
  it('sorts by total score, highest first, unscored last, older first on ties', () => {
    const picks = [
      { id: 'a', total_score: 76, created_at: '2026-10-04T10:00:00Z' },
      { id: 'b', total_score: null, created_at: '2026-10-04T09:00:00Z' },
      { id: 'c', total_score: 92, created_at: '2026-10-04T11:00:00Z' },
      { id: 'd', total_score: 76, created_at: '2026-10-04T08:00:00Z' },
    ];
    expect(sortPicks(picks).map((p) => p.id)).toEqual(['c', 'd', 'a', 'b']);
    expect(picks.map((p) => p.id)).toEqual(['a', 'b', 'c', 'd']); // input untouched
  });
});

describe('spend vs cap', () => {
  it('is fine below 80% and projects the month from the pace so far', () => {
    const s = spendState({ committed: 1500, cap: 6000, day_of_month: 10, days_in_month: 31 });
    expect(s.tone).toBe('ok');
    expect(s.pct).toBeCloseTo(25);
    expect(s.projected).toBe(4650);
    expect(s.projectedTone).toBe('ok');
  });
  it('warns at exactly 80% (integer arithmetic, like studio health) and not at 4,799', () => {
    expect(spendState({ committed: 4800, cap: 6000, day_of_month: 20, days_in_month: 30 }).tone).toBe('warn');
    expect(spendState({ committed: 4799, cap: 6000, day_of_month: 20, days_in_month: 30 }).tone).toBe('ok');
  });
  it('is over at the cap, and flags a projection past it', () => {
    expect(spendState({ committed: 6000, cap: 6000, day_of_month: 28, days_in_month: 30 }).tone).toBe('over');
    expect(spendState({ committed: 3000, cap: 6000, day_of_month: 10, days_in_month: 30 }).projectedTone).toBe('over');
  });
  it('has no percentage with a cap of 0', () => {
    const s = spendState({ committed: 0, cap: 0, day_of_month: 1, days_in_month: 31 });
    expect(s.pct).toBeNull();
    expect(s.tone).toBe('ok');
  });
});

describe('owner links: the canonical URL (mirrors studio.favorites.parse_video_url)', () => {
  it('canonicalises TikTok, Instagram Reels and YouTube Shorts', () => {
    expect(canonicalVideoUrl('https://m.tiktok.com/@Lola.TheStaffy/video/7679128537311251734?lang=en')).toEqual({
      platform: 'tiktok',
      url: 'https://www.tiktok.com/@lola.thestaffy/video/7679128537311251734',
    });
    expect(canonicalVideoUrl('instagram.com/mrcharliebrowne/reel/Dd1koUkoXgq?igsh=x')).toEqual({
      platform: 'instagram',
      url: 'https://www.instagram.com/reel/Dd1koUkoXgq/',
    });
    expect(canonicalVideoUrl(' https://youtube.com/shorts/abc_DEF-1/ ')).toEqual({
      platform: 'youtube',
      url: 'https://www.youtube.com/shorts/abc_DEF-1',
    });
  });
  it('refuses short links and anything that is not a video page', () => {
    expect(() => canonicalVideoUrl('https://vm.tiktok.com/ZMabc/')).toThrow(/short links/);
    expect(() => canonicalVideoUrl('https://www.tiktok.com/t/ZT8abc/')).toThrow(/short links/);
    expect(() => canonicalVideoUrl('https://youtu.be/abc')).toThrow(/short links/);
    expect(() => canonicalVideoUrl('https://www.tiktok.com/@someone')).toThrow(/not a supported video URL/);
    expect(() => canonicalVideoUrl('ftp://www.tiktok.com/@a/video/1')).toThrow(/not a supported video URL/);
    expect(() => canonicalVideoUrl('')).toThrow(/url is required/);
  });
});

describe('the Today board: one row per channel', () => {
  const now = Date.parse('2026-10-06T12:00:00Z'); // Tue 13:00 London
  const ch = (over: Record<string, unknown>) => ({
    account_id: 'a', character_slug: 'biscuit', platform: 'tiktok', handle: '@biscuit.moves', connected: true,
    next_slot: '2026-10-06T18:00:00Z', today_posts: [], ...over,
  });
  it('shows today\'s post with its time and status', () => {
    const [row] = boardRows(
      [ch({ today_posts: [{ post_id: 'p', clip_id: 'c', scheduled_for: '2026-10-06T18:00:00Z', status: 'scheduled', hook: 'h', mode: 'recreate', url: null }] })],
      [], now,
    );
    expect(row).toMatchObject({ time: '19:00', status: 'SCHEDULED', tone: 'neutral', clipId: 'c', hook: 'h', today: true });
  });
  it('says NEEDS YOU when the slot is today, nothing is booked and a clip of the character waits', () => {
    const [row] = boardRows([ch({})], [{ id: 'q', character_slug: 'biscuit', hook: 'w' }], now);
    expect(row).toMatchObject({ time: '19:00', status: 'NEEDS YOU', tone: 'action', clipId: 'q' });
  });
  it('says NO CLIP when the slot is today and nothing waits', () => {
    expect(boardRows([ch({})], [], now)[0]).toMatchObject({ status: 'NO CLIP', tone: 'warn' });
  });
  it('shows the next cadence day when the slot is not today', () => {
    expect(boardRows([ch({ next_slot: '2026-10-07T18:00:00Z' })], [], now)[0]).toMatchObject({
      time: '19:00', day: 'Wed', status: 'NEXT', today: false,
    });
  });
  it('says NOT LINKED for an account without a Postiz connection', () => {
    expect(boardRows([ch({ connected: false })], [], now)[0]).toMatchObject({ status: 'NOT LINKED', tone: 'muted' });
  });
  it('maps posted, failed and needs_check posts', () => {
    const post = (status: string) => ch({ today_posts: [{ post_id: 'p', clip_id: 'c', scheduled_for: '2026-10-06T18:00:00Z', status, hook: null, mode: 'dropin', url: null }] });
    expect(boardRows([post('posted')], [], now)[0]).toMatchObject({ status: 'POSTED', tone: 'live' });
    expect(boardRows([post('failed')], [], now)[0]).toMatchObject({ status: 'FAILED', tone: 'alert' });
    expect(boardRows([post('needs_check')], [], now)[0]).toMatchObject({ status: 'CHECK', tone: 'alert' });
    expect(boardRows([post('posting')], [], now)[0]).toMatchObject({ status: 'POSTING', tone: 'live' });
  });
  it('orders rows by time, then character, then platform', () => {
    const rows = boardRows(
      [
        ch({ account_id: 'r-ig', character_slug: 'reginald', platform: 'instagram', next_slot: '2026-10-06T18:30:00Z' }),
        ch({ account_id: 'b-ig', platform: 'instagram' }),
        ch({ account_id: 'b-tt' }),
      ],
      [], now,
    );
    expect(rows.map((r) => r.accountId)).toEqual(['b-ig', 'b-tt', 'r-ig']);
  });
});
