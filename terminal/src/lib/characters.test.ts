// The Characters page, the "Make it" sheet and the Scanner card: the rules behind them, pure and tested.
import { describe, expect, it } from 'vitest';
import { DemoBackend } from '../demo/backend';
import { londonWallToIso } from './format';
import {
  NOTE_MAX,
  PIPELINE_LIMITS,
  SCAN_STALL_MS,
  VIDIQ_MONTHLY_CREDITS,
  channelSlots,
  goLiveChecklist,
  makeItPayload,
  nextScanAt,
  nextScanLabel,
  pipelineFor,
  scannerStatus,
  tabIndexAfter,
} from './rules';
import type { Channel, Character, LibraryClip, Pick, PickHistory, QueueClip, RunRow } from './types';

const HOUR = 3_600_000;

// ---- the go-live checklist ----------------------------------------------------------------------

const char = (over: Partial<Character> = {}): Character => ({
  slug: 'biscuit', name: 'Biscuit', status: 'designing', bodies: ['biped'], setup: {}, accounts: [], ...over,
});
const acct = (platform: 'tiktok' | 'instagram', over: Partial<Character['accounts'][number]> = {}) => ({
  platform, handle: platform === 'tiktok' ? '@biscuit.moves' : 'biscuit.moves', has_postiz: true, mode: 'approval' as const, ...over,
});

describe('goLiveChecklist', () => {
  it('a character with nothing yet fails every row and is not ready', () => {
    const c = goLiveChecklist(char());
    expect(c.items.map((i) => [i.id, i.done])).toEqual([
      ['tiktok', false], ['instagram', false], ['postiz', false], ['closeup', false], ['live', false],
    ]);
    expect(c.items.map((i) => i.label)).toEqual([
      'TikTok account', 'Instagram account', 'Postiz connected', 'Close-up shot ready', 'Live',
    ]);
    expect([c.done, c.total, c.ready]).toEqual([0, 5, false]);
  });

  it('an account row ticks its platform; Postiz needs every account connected', () => {
    const half = goLiveChecklist(char({ accounts: [acct('tiktok'), acct('instagram', { has_postiz: false })] }));
    expect(half.items.map((i) => i.done)).toEqual([true, true, false, false, false]);
    expect(half.items[2].detail).toBe('1 of 2 connected');
    const all = goLiveChecklist(char({ accounts: [acct('tiktok'), acct('instagram')] }));
    expect(all.items[2]).toMatchObject({ done: true, detail: '2 of 2 connected' });
  });

  it('no accounts is never "connected", and an account without a handle is not an account yet', () => {
    expect(goLiveChecklist(char()).items[2]).toMatchObject({ done: false, detail: 'no accounts yet' });
    const c = goLiveChecklist(char({ accounts: [acct('tiktok', { handle: null }), acct('instagram', { handle: '  ' })] }));
    expect(c.items.slice(0, 2).map((i) => i.done)).toEqual([false, false]);
  });

  it('the close-up follows setup.closeup and Live follows the status', () => {
    expect(goLiveChecklist(char({ setup: { closeup: true } })).items[3].done).toBe(true);
    expect(goLiveChecklist(char({ setup: { closeup: false } })).items[3].done).toBe(false);
    expect(goLiveChecklist(char({ status: 'live' })).items[4].done).toBe(true);
    expect(goLiveChecklist(char({ status: 'paused' })).items[4].done).toBe(false);
  });

  it('ready = everything before Live is done (the owner may flip it); all five is complete', () => {
    const ready = goLiveChecklist(char({ setup: { closeup: true }, accounts: [acct('tiktok'), acct('instagram')] }));
    expect([ready.done, ready.ready]).toEqual([4, true]);
    const live = goLiveChecklist(char({ status: 'live', setup: { closeup: true }, accounts: [acct('tiktok'), acct('instagram')] }));
    expect([live.done, live.total, live.ready]).toEqual([5, 5, true]);
  });

  it('names the planned handle on an account row that does not exist yet', () => {
    const c = goLiveChecklist(char({ setup: { planned_handles: { tiktok: '@biscuit.moves', instagram: null } } }));
    expect(c.items[0].detail).toBe('planned @biscuit.moves');
    expect(c.items[1].detail).toBe('not created yet');
    const real = goLiveChecklist(char({ accounts: [acct('tiktok')] }));
    expect(real.items[0].detail).toBe('@biscuit.moves');
  });
});

describe('channelSlots', () => {
  const channel = (platform: 'tiktok' | 'instagram', slug = 'biscuit') => ({ account_id: `${slug}-${platform}`, character_slug: slug, platform }) as Channel;

  it('always gives both platforms, sorted as the Channels page always did, an existing account first-class', () => {
    const slots = channelSlots(char({ setup: { planned_handles: { tiktok: '@b', instagram: null } } }), [
      channel('tiktok'), channel('tiktok', 'reginald'), channel('instagram', 'reginald'),
    ]);
    expect(slots.map((s) => s.platform)).toEqual(['instagram', 'tiktok']);
    expect(slots[0].channel).toBeNull(); // Biscuit has no Instagram account yet
    expect(slots[0].planned).toBeNull();
    expect(slots[1].channel?.account_id).toBe('biscuit-tiktok');
    expect(slots[1].planned).toBe('@b');
  });

  it('a character with no accounts shows two not-connected slots', () => {
    const slots = channelSlots(char(), []);
    expect(slots.map((s) => [s.platform, s.channel])).toEqual([['instagram', null], ['tiktok', null]]);
  });
});

// ---- the pipeline ---------------------------------------------------------------------------------

const pick = (id: string, over: Partial<Pick> = {}): Pick => ({
  id, url: `https://www.tiktok.com/@x/video/${id}`, platform: 'tiktok', creator_handle: '@x', views: 1000, outlier_x: 5, origin: 'scan',
  character_slug: 'biscuit', character_name: 'Biscuit', intended_character: null, total_score: 70, virality: null, reach: null,
  freshness: null, fit: null, feasibility: null, saturation: null, proposed_mode: 'recreate', hook: `hook ${id}`, prop: null,
  concept: null, enhancement: null, needs: null, decision: null, hold_reason: null, note: null, status: 'new',
  created_at: '2026-10-05T08:00:00Z', owner_note: null, owner_mode: null, owner_presence: null, ...over,
});
const past = (id: string, over: Partial<PickHistory> = {}): PickHistory => ({
  id, url: `https://www.tiktok.com/@x/video/${id}`, platform: 'tiktok', creator_handle: '@x', views: 1000, outlier_x: 5, origin: 'scan',
  character_slug: 'biscuit', character_name: 'Biscuit', total_score: 70, hook: `hook ${id}`, concept: null, decision: null, note: null,
  status: 'approved', created_at: '2026-10-05T08:00:00Z', clip_id: null, clip_state: null, owner_note: null, owner_mode: null,
  owner_presence: null, ...over,
});
const clip = (id: string, state: LibraryClip['state'], over: Partial<LibraryClip> = {}): LibraryClip => ({
  id, character_slug: 'biscuit', character_name: 'Biscuit', mode: 'recreate', state, hook: `clip ${id}`, caption: null, master_path: null,
  reject_reason: null, created_at: '2026-10-05T07:00:00Z', cost_credits: null, outlier_x: null, format_id: null, posts: [], platforms: [],
  views: null, posted_at: null, ...over,
});
const queued = (id: string, over: Partial<QueueClip> = {}): QueueClip => ({
  id, character_slug: 'biscuit', character_name: 'Biscuit', mode: 'recreate', state: 'awaiting_approval', master_path: 'm.mp4', hook: `queue ${id}`,
  caption: null, hashtags: [], cost_credits: 160, qa: {}, features: {}, created_at: '2026-10-05T07:00:00Z', source_kind: null, source_url: null,
  source_credit: null, source_trend: null,
  targets: [{ account_id: 'a', platform: 'tiktok', handle: '@b', mode: 'approval' }, { account_id: 'b', platform: 'instagram', handle: 'b', mode: 'approval' }],
  next_slot: '2026-10-06T18:00:00Z', pick_id: null, pick_url: null, blocked_reason: null, ...over,
});
const data = (over: Partial<Parameters<typeof pipelineFor>[1]> = {}) => ({ picks: [], history: [], queue: [], library: [], ...over });

describe('pipelineFor: Proposed', () => {
  it('holds this character’s new, approved and analysed picks, and nobody else’s', () => {
    const p = pipelineFor('biscuit', data({
      picks: [pick('n1'), pick('other', { character_slug: 'reginald' }), pick('nobody', { character_slug: null, intended_character: 'outsider' })],
      history: [
        past('a1', { status: 'approved' }), past('an', { status: 'analysed' }), past('q', { status: 'queued' }),
        past('m', { status: 'made' }), past('s', { status: 'skipped' }), past('r', { status: 'approved', character_slug: 'reginald' }),
      ],
    }));
    expect(p.proposed.items.map((i) => i.id).sort()).toEqual(['a1', 'an', 'n1']);
    expect(p.proposed.total).toBe(3);
  });

  it('puts the ones waiting for the owner first, then by score, then oldest', () => {
    const p = pipelineFor('biscuit', data({
      picks: [pick('lo', { total_score: 60 }), pick('hi', { total_score: 90 }), pick('none', { total_score: null })],
      history: [past('appr', { status: 'approved', total_score: 99 }), past('ana', { status: 'analysed', total_score: 95 })],
    }));
    expect(p.proposed.items.map((i) => i.id)).toEqual(['hi', 'lo', 'none', 'appr', 'ana']);
    const ties = pipelineFor('biscuit', data({
      picks: [pick('late', { created_at: '2026-10-05T09:00:00Z' }), pick('early', { created_at: '2026-10-05T07:00:00Z' })],
    }));
    expect(ties.proposed.items.map((i) => i.id)).toEqual(['early', 'late']);
  });

  it('only a new pick can be made; each carries how he is looped in and the owner’s note', () => {
    const p = pipelineFor('biscuit', data({
      picks: [pick('n', { owner_mode: null, hold_reason: 'needs two bodies' })],
      history: [past('a', { owner_mode: 'dropin', owner_presence: 'star', owner_note: 'slow-mo on the drop' })],
    }));
    const [n, a] = p.proposed.items;
    expect([n.canMakeIt, n.held, n.ownerMode]).toEqual([true, true, null]);
    expect([a.canMakeIt, a.status, a.ownerMode, a.ownerPresence, a.ownerNote]).toEqual([false, 'approved', 'dropin', 'star', 'slow-mo on the drop']);
    expect(n.pick?.id).toBe('n'); // the sheet needs the whole pick
    expect(a.pick).toBeNull();
  });

  it('shows at most PIPELINE_LIMITS.proposed and still counts them all', () => {
    const many = Array.from({ length: PIPELINE_LIMITS.proposed + 4 }, (_, i) => pick(`p${i}`, { total_score: 100 - i }));
    const p = pipelineFor('biscuit', data({ picks: many }));
    expect(p.proposed.items).toHaveLength(PIPELINE_LIMITS.proposed);
    expect(p.proposed.total).toBe(PIPELINE_LIMITS.proposed + 4);
    expect(p.proposed.items[0].id).toBe('p0');
  });
});

describe('pipelineFor: In production', () => {
  it('holds this character’s clips in every state before approval, newest first, with age and credits', () => {
    const states = ['planned', 'generating', 'gen_failed', 'generated', 'qa_failed', 'qa_passed', 'mastered'] as const;
    const library = [
      ...states.map((s, i) => clip(s, s, { created_at: `2026-10-05T0${i + 1}:00:00Z`, cost_credits: 100 + i })),
      clip('other', 'generating', { character_slug: 'reginald' }),
      clip('done', 'posted'), clip('sched', 'scheduled'), clip('rej', 'rejected'), clip('drop', 'dropped'), clip('await', 'awaiting_approval'),
    ];
    const p = pipelineFor('biscuit', data({ library }));
    expect(p.production.items.map((i) => i.id)).toEqual([...states].reverse());
    expect(p.production.total).toBe(7);
    expect(p.production.items[0]).toMatchObject({ id: 'mastered', state: 'mastered', credits: 106, createdAt: '2026-10-05T07:00:00Z' });
  });

  it('marks a failed state so the card can say so', () => {
    const p = pipelineFor('biscuit', data({ library: [clip('f', 'gen_failed'), clip('q', 'qa_failed'), clip('g', 'generating')] }));
    expect(p.production.items.map((i) => [i.id, i.failed]).sort()).toEqual([['f', true], ['g', false], ['q', true]]);
  });
});

describe('pipelineFor: Waiting / scheduled', () => {
  it('lists the clips awaiting approval first (with the Queue link target), then scheduled ones by slot', () => {
    const library = [
      clip('s2', 'scheduled', { posts: [{ post_id: 'p', platform: 'tiktok', handle: '@b', status: 'scheduled', scheduled_for: '2026-10-08T18:00:00Z', url: null, views: null, likes: null, comments: null, shares: null, saves: null, captured_at: null }] }),
      clip('s1', 'scheduled', {
        posts: [
          { post_id: 'a', platform: 'tiktok', handle: '@b', status: 'scheduled', scheduled_for: '2026-10-07T18:00:00Z', url: null, views: null, likes: null, comments: null, shares: null, saves: null, captured_at: null },
          { post_id: 'b', platform: 'instagram', handle: 'b', status: 'scheduled', scheduled_for: '2026-10-07T18:00:00Z', url: null, views: null, likes: null, comments: null, shares: null, saves: null, captured_at: null },
        ],
      }),
      clip('other', 'scheduled', { character_slug: 'reginald' }),
    ];
    const p = pipelineFor('biscuit', data({ queue: [queued('q1'), queued('q2', { character_slug: 'reginald' })], library }));
    expect(p.waiting.items.map((i) => [i.id, i.kind])).toEqual([['q1', 'awaiting_approval'], ['s1', 'scheduled'], ['s2', 'scheduled']]);
    expect(p.waiting.items[0]).toMatchObject({ at: '2026-10-06T18:00:00Z', platforms: ['instagram', 'tiktok'], blocked: null });
    expect(p.waiting.items[1]).toMatchObject({ at: '2026-10-07T18:00:00Z', platforms: ['instagram', 'tiktok'] });
    expect(p.waiting.total).toBe(3);
  });

  it('carries why a clip cannot be approved yet', () => {
    const p = pipelineFor('biscuit', data({ queue: [queued('q', { blocked_reason: 'no master file yet' })] }));
    expect(p.waiting.items[0].blocked).toBe('no master file yet');
  });
});

describe('pipelineFor: Posted', () => {
  const posted = (id: string, at: string | null, over: Partial<LibraryClip> = {}) =>
    clip(id, 'posted', { posted_at: at, platforms: ['instagram', 'tiktok'], views: 1000, outlier_x: 2.5, ...over });

  it('is the last 5 posted clips, latest first, with platforms, views and outlier ×', () => {
    const library = Array.from({ length: 7 }, (_, i) => posted(`c${i}`, `2026-10-0${i + 1}T18:00:00Z`));
    const p = pipelineFor('biscuit', data({ library }));
    expect(PIPELINE_LIMITS.posted).toBe(5);
    expect(p.posted.items.map((i) => i.id)).toEqual(['c6', 'c5', 'c4', 'c3', 'c2']);
    expect(p.posted.total).toBe(7);
    expect(p.posted.items[0]).toMatchObject({ postedAt: '2026-10-07T18:00:00Z', platforms: ['instagram', 'tiktok'], views: 1000, outlierX: 2.5 });
  });

  it('falls back to the creation date when no post time is known, and ignores other states and characters', () => {
    const p = pipelineFor('biscuit', data({
      library: [posted('old', null, { created_at: '2026-09-01T00:00:00Z' }), posted('new', '2026-10-01T00:00:00Z'), posted('r', '2026-10-02T00:00:00Z', { character_slug: 'reginald' }), clip('g', 'generating')],
    }));
    expect(p.posted.items.map((i) => i.id)).toEqual(['new', 'old']);
  });
});

describe('pipelineFor: which stage opens first', () => {
  it('is the first stage that has something, in pipeline order', () => {
    expect(pipelineFor('biscuit', data()).firstOpen).toBeNull();
    expect(pipelineFor('biscuit', data({ library: [clip('p', 'posted', { posted_at: '2026-10-01T00:00:00Z' })] })).firstOpen).toBe('posted');
    expect(pipelineFor('biscuit', data({ queue: [queued('q')], library: [clip('p', 'posted')] })).firstOpen).toBe('waiting');
    expect(pipelineFor('biscuit', data({ library: [clip('g', 'generating'), clip('p', 'posted')] })).firstOpen).toBe('production');
    expect(pipelineFor('biscuit', data({ picks: [pick('n')], library: [clip('g', 'generating')] })).firstOpen).toBe('proposed');
  });
});

// ---- the Make-it sheet's decision -------------------------------------------------------------------

describe('makeItPayload', () => {
  const ctx = { pickCharacter: 'reginald', characters: ['biscuit', 'reginald'] };
  const base = { character: 'reginald', note: '', mode: 'analyst' as const, presence: 'featured' as const };

  it('one character, no note, the analyst decides: only the character goes', () => {
    expect(makeItPayload(base, ctx)).toEqual({
      ok: true, characterSlug: 'reginald',
      extras: { alsoCharacter: null, ownerNote: null, ownerMode: null, ownerPresence: null, ownerProps: null, ownerMusic: null },
      summary: 'Approved for Reginald: it joins the production queue',
    });
  });

  it('Both approves for the pick’s own character and files the other one as also_character', () => {
    expect(makeItPayload({ ...base, character: 'both' }, ctx)).toMatchObject({
      ok: true, characterSlug: 'reginald', extras: { alsoCharacter: 'biscuit' },
      summary: 'Approved for Reginald and Biscuit: one clip each',
    });
    // a pick with no character yet: the first character is primary, the other is also
    expect(makeItPayload({ ...base, character: 'both' }, { ...ctx, pickCharacter: null })).toMatchObject({
      ok: true, characterSlug: 'biscuit', extras: { alsoCharacter: 'reginald' },
    });
    // choosing a character other than the analyst's is a plain override
    expect(makeItPayload({ ...base, character: 'biscuit' }, ctx)).toMatchObject({ characterSlug: 'biscuit', extras: { alsoCharacter: null } });
  });

  it('Both needs exactly two characters', () => {
    expect(makeItPayload({ ...base, character: 'both' }, { ...ctx, characters: ['biscuit'] })).toMatchObject({ ok: false });
    expect(makeItPayload({ ...base, character: 'both' }, { ...ctx, characters: ['a', 'b', 'c'] })).toMatchObject({ ok: false });
  });

  it('the note is trimmed, blank is none, and 280 characters is the limit', () => {
    expect(makeItPayload({ ...base, note: '  slow-mo on the drop  ' }, ctx)).toMatchObject({ extras: { ownerNote: 'slow-mo on the drop' } });
    expect(makeItPayload({ ...base, note: '   ' }, ctx)).toMatchObject({ extras: { ownerNote: null } });
    expect(NOTE_MAX).toBe(280);
    expect(makeItPayload({ ...base, note: 'x'.repeat(280) }, ctx)).toMatchObject({ ok: true });
    expect(makeItPayload({ ...base, note: 'x'.repeat(281) }, ctx)).toMatchObject({ ok: false });
    expect(makeItPayload({ ...base, note: ` ${'x'.repeat(280)} ` }, ctx)).toMatchObject({ ok: true }); // trimmed first, like the database
  });

  it('Analyst decides sends no mode and no presence, whatever the presence control says', () => {
    expect(makeItPayload({ ...base, mode: 'analyst', presence: 'star' }, ctx)).toMatchObject({ extras: { ownerMode: null, ownerPresence: null } });
  });

  it('Recreate sends the mode and never a presence', () => {
    expect(makeItPayload({ ...base, mode: 'recreate', presence: 'star' }, ctx)).toMatchObject({ extras: { ownerMode: 'recreate', ownerPresence: null } });
  });

  it('Drop-in sends the mode with his part (Featured unless changed)', () => {
    expect(makeItPayload({ ...base, mode: 'dropin' }, ctx)).toMatchObject({ extras: { ownerMode: 'dropin', ownerPresence: 'featured' } });
    for (const part of ['cameo', 'featured', 'star'] as const) {
      expect(makeItPayload({ ...base, mode: 'dropin', presence: part }, ctx)).toMatchObject({ extras: { ownerMode: 'dropin', ownerPresence: part } });
    }
  });

  it('without a character it says so instead of sending anything', () => {
    expect(makeItPayload({ ...base, character: null }, ctx)).toEqual({ ok: false, reason: 'Choose a character first' });
  });

  it('refuses a character the studio does not have', () => {
    expect(makeItPayload({ ...base, character: 'nobody' }, ctx)).toMatchObject({ ok: false });
  });
});

describe('tabIndexAfter (the sheet’s focus trap)', () => {
  it('wraps forwards and backwards inside the sheet', () => {
    expect(tabIndexAfter(0, 4, false)).toBe(1);
    expect(tabIndexAfter(3, 4, false)).toBe(0);
    expect(tabIndexAfter(0, 4, true)).toBe(3);
    expect(tabIndexAfter(2, 4, true)).toBe(1);
  });
  it('an element outside the sheet (-1) enters at the first or the last', () => {
    expect(tabIndexAfter(-1, 4, false)).toBe(0);
    expect(tabIndexAfter(-1, 4, true)).toBe(3);
  });
  it('no focusable element: nothing to move to', () => {
    expect(tabIndexAfter(-1, 0, false)).toBe(-1);
  });
});

// ---- the Scanner ------------------------------------------------------------------------------------

const NOW = Date.parse('2026-10-06T10:00:00Z'); // Tue 11:00 London (BST)
const run = (over: Partial<RunRow> = {}): RunRow => ({
  id: Math.random().toString(36).slice(2), kind: 'daily', started_at: '2026-10-06T07:00:00Z', finished_at: '2026-10-06T07:40:00Z',
  status: 'ok', summary: null, details: null, ...over,
});
const scanRun = (over: Partial<RunRow> = {}, scan = {}) =>
  run({
    details: { scan: { queries: ['biscuit #2 concept'], outliers: 9, picks_added: 4, auto_approved: 1, held: 1, skipped: 2, vidiq_credits: 15, ...scan } },
    ...over,
  });

describe('scannerStatus', () => {
  it('no daily run at all: no scan yet', () => {
    const s = scannerStatus([], NOW);
    expect(s).toMatchObject({ state: 'none', headline: 'No scan yet', last: null, creditsMonth: 0, creditsLimit: VIDIQ_MONTHLY_CREDITS });
    expect(VIDIQ_MONTHLY_CREDITS).toBe(150);
    expect(scannerStatus([run({ kind: 'weekly', details: { scan: { outliers: 3 } } })], NOW).state).toBe('none'); // only daily runs scan
  });

  it('runs that never scanned are not a scan either', () => {
    expect(scannerStatus([run({ details: {} }), run({ details: null })], NOW)).toMatchObject({ state: 'none', headline: 'No scan yet' });
  });

  it('an unfinished daily run under 3 hours old is "Scanning now"', () => {
    const s = scannerStatus([run({ started_at: '2026-10-06T09:40:00Z', finished_at: null })], NOW);
    expect(s).toMatchObject({ state: 'scanning', headline: 'Scanning now', startedAt: '2026-10-06T09:40:00Z', tone: 'live' });
  });

  it('an unfinished run turns "stalled" at 3 hours, not before', () => {
    const open = (ago: number) => run({ started_at: new Date(NOW - ago).toISOString(), finished_at: null });
    expect(SCAN_STALL_MS).toBe(3 * HOUR);
    expect(scannerStatus([open(3 * HOUR - 1)], NOW).state).toBe('scanning');
    const s = scannerStatus([open(3 * HOUR)], NOW);
    expect(s).toMatchObject({ state: 'stalled', tone: 'alert' });
    expect(s.headline).toMatch(/stalled/i);
  });

  it('shows the last scan with its London time and status', () => {
    const s = scannerStatus([scanRun({ started_at: '2026-10-06T07:00:00Z', finished_at: '2026-10-06T07:41:00Z' })], NOW);
    expect(s.state).toBe('finished');
    expect(s.headline).toBe('Last scan Tue 6 Oct 08:41 · ok'); // 07:41 UTC = 08:41 BST
    expect(s.last?.scan).toEqual({ queries: ['biscuit #2 concept'], outliers: 9, picks_added: 4, auto_approved: 1, held: 1, skipped: 2, vidiq_credits: 15 });
    expect(s.creditsRun).toBe(15);
    expect(s.tone).toBe('neutral');
  });

  it('names how a scan ended: ok, stopped on the budget, failed', () => {
    expect(scannerStatus([scanRun({ status: 'budget_stop' })], NOW).headline).toMatch(/stopped on the budget cap$/);
    const failed = scannerStatus([scanRun({ status: 'error' })], NOW);
    expect(failed.headline).toMatch(/failed$/);
    expect(failed.tone).toBe('alert');
  });

  it('fills the numbers a scan did not log with zero', () => {
    const s = scannerStatus([run({ details: { scan: { outliers: 3 } } })], NOW);
    expect(s.last?.scan).toEqual({ queries: [], outliers: 3, picks_added: 0, auto_approved: 0, held: 0, skipped: 0, vidiq_credits: 0 });
  });

  it('a later finished run without a scan does not hide the last scan', () => {
    const monday = run({ started_at: '2026-10-06T09:00:00Z', finished_at: '2026-10-06T09:20:00Z', details: {} });
    const s = scannerStatus([scanRun({ started_at: '2026-10-04T07:00:00Z', finished_at: '2026-10-04T07:30:00Z' }), monday], NOW);
    expect(s.state).toBe('finished');
    expect(s.headline).toBe('Last scan Sun 4 Oct 08:30 · ok');
  });

  it('while a new run is in progress the previous scan’s numbers stay visible', () => {
    const s = scannerStatus([scanRun({ started_at: '2026-10-04T07:00:00Z', finished_at: '2026-10-04T07:30:00Z' }), run({ started_at: '2026-10-06T09:50:00Z', finished_at: null })], NOW);
    expect(s.state).toBe('scanning');
    expect(s.last?.scan.picks_added).toBe(4);
  });

  it('the closing row of a run ends "Scanning now" even though its open row is still there', () => {
    const open = run({ started_at: '2026-10-06T09:00:00Z', finished_at: null });
    const closing = scanRun({ started_at: '2026-10-06T09:00:00Z', finished_at: '2026-10-06T09:35:00Z' });
    expect(scannerStatus([open, closing], NOW).state).toBe('finished');
    expect(scannerStatus([closing, open], NOW).state).toBe('finished'); // whatever the order the rows arrive in
  });

  it('a long-dead open row from an earlier day does not hide a newer finished run', () => {
    const dead = run({ started_at: '2026-10-03T07:00:00Z', finished_at: null });
    const s = scannerStatus([dead, scanRun({ started_at: '2026-10-04T07:00:00Z', finished_at: '2026-10-04T07:30:00Z' })], NOW);
    expect(s.state).toBe('finished');
  });

  it('adds up this London month’s vidIQ credits: the scan’s, and a bare top-level count of a day that did not scan', () => {
    const s = scannerStatus(
      [
        scanRun({ started_at: '2026-10-01T07:00:00Z', finished_at: '2026-10-01T07:30:00Z' }, { vidiq_credits: 20 }),
        run({ started_at: '2026-10-02T07:00:00Z', finished_at: '2026-10-02T07:20:00Z', details: { vidiq_credits: 10 } }),
        scanRun({ started_at: '2026-10-06T07:00:00Z', finished_at: '2026-10-06T07:30:00Z' }, { vidiq_credits: 15 }),
        scanRun({ started_at: '2026-09-30T07:00:00Z', finished_at: '2026-09-30T07:30:00Z' }, { vidiq_credits: 99 }), // last month
        run({ kind: 'weekly', details: { vidiq_credits: 7 } }),
        run({ started_at: '2026-10-03T07:00:00Z', details: { scan: { vidiq_credits: 'lots' } } as never }), // not a number: counted as 0
      ],
      NOW,
    );
    expect(s.creditsMonth).toBe(45);
  });

  it('the month is the London month: a run just after midnight BST on 1 October counts for October', () => {
    const midnight = scanRun({ started_at: '2026-09-30T23:30:00Z', finished_at: '2026-09-30T23:50:00Z' }, { vidiq_credits: 5 }); // 00:30 BST on 1 Oct
    expect(scannerStatus([midnight], NOW).creditsMonth).toBe(5);
  });
});

describe('the next scan', () => {
  it('is the next 08:00 London on a scan day (one search each weekday, Mon to Fri)', () => {
    // Tue 6 Oct 11:00 London: today's 08:00 has passed, so Wed 7 Oct
    expect(nextScanAt(NOW)).toBe(londonWallToIso('2026-10-07T08:00'));
    // Tue 6 Oct 06:30 London: today 08:00 is still ahead
    expect(nextScanAt(Date.parse(londonWallToIso('2026-10-06T06:30')))).toBe(londonWallToIso('2026-10-06T08:00'));
    // Thu 8 Oct 08:00 sharp: strictly after, so Fri 9 Oct
    expect(nextScanAt(Date.parse(londonWallToIso('2026-10-08T08:00')))).toBe(londonWallToIso('2026-10-09T08:00'));
    // Fri 9 Oct evening: no scan at the weekend -> Mon 12 Oct
    expect(nextScanAt(Date.parse(londonWallToIso('2026-10-09T20:00')))).toBe(londonWallToIso('2026-10-12T08:00'));
  });

  it('keeps 08:00 London across the clock change (GMT from 25 Oct)', () => {
    const iso = nextScanAt(Date.parse(londonWallToIso('2026-10-24T09:00'))); // Sat 24 Oct
    expect(iso).toBe('2026-10-26T08:00:00.000Z'); // Mon 26 Oct: GMT again, 08:00 London = 08:00 UTC
  });

  it('is labelled with the schedule once a character is live, and "not scheduled yet" before', () => {
    expect(nextScanLabel(NOW, true)).toBe('Next scan Wed 7 Oct 08:00');
    expect(nextScanLabel(NOW, false)).toMatch(/^Not scheduled yet/);
    expect(nextScanLabel(NOW, false)).toMatch(/Monday to Friday at 08:00/);
  });
});

// ---- the demo follows the same rules as the RPC ---------------------------------------------------------

describe('the demo backend’s decidePick (what the sheet calls)', () => {
  const NOW_MS = Date.parse('2026-10-06T12:00:00Z');
  const fresh = async () => {
    const demo = new DemoBackend(() => NOW_MS);
    return { demo, snap: await demo.load() };
  };

  it('Both approves the pick and files one sibling for the other character, with the owner’s instructions', async () => {
    const { demo, snap } = await fresh();
    const p = snap.picks.find((x) => x.character_slug === 'reginald')!;
    await demo.decidePick(p.id, 'approve', null, 'reginald', { alsoCharacter: 'biscuit', ownerNote: ' slow-mo on the drop ', ownerMode: 'dropin', ownerPresence: 'star' });
    const after = await demo.load();
    expect(after.picks.find((x) => x.id === p.id)).toBeUndefined();
    const rows = after.history.filter((h) => h.url === p.url);
    expect(rows.map((r) => r.character_slug).sort()).toEqual(['biscuit', 'reginald']);
    for (const r of rows) {
      expect([r.status, r.owner_note, r.owner_mode, r.owner_presence]).toEqual(['approved', 'slow-mo on the drop', 'dropin', 'star']);
    }
  });

  it('Both twice reuses the sibling', async () => {
    const { demo, snap } = await fresh();
    const p = snap.picks.find((x) => x.character_slug === 'biscuit')!;
    await demo.decidePick(p.id, 'approve', null, 'biscuit', { alsoCharacter: 'reginald' });
    await demo.decidePick(p.id, 'approve', null, 'biscuit', { alsoCharacter: 'reginald', ownerNote: 'again' });
    const rows = (await demo.load()).history.filter((h) => h.url === p.url);
    expect(rows).toHaveLength(2);
    expect(rows.every((r) => r.owner_note === 'again')).toBe(true);
  });

  it('stores presence only for a Drop-in, keeps a value on a blank, and a skip stores nothing', async () => {
    const { demo, snap } = await fresh();
    const [a, b, c] = snap.picks.filter((x) => x.character_slug === 'reginald');
    await demo.decidePick(a.id, 'approve', null, null, { ownerMode: 'recreate', ownerPresence: 'star' });
    await demo.decidePick(b.id, 'approve', null, null, { ownerNote: '   ' });
    await demo.decidePick(c.id, 'skip', 'seen it everywhere', null, { ownerNote: 'ignored' });
    const h = (await demo.load()).history;
    const row = (id: string) => h.find((x) => x.id === id)!;
    expect([row(a.id).owner_mode, row(a.id).owner_presence]).toEqual(['recreate', null]);
    expect([row(b.id).owner_note, row(b.id).owner_mode]).toEqual([null, null]);
    expect([row(c.id).status, row(c.id).owner_note]).toEqual(['skipped', null]);
  });

  it('refuses what the database refuses, before anything is written', async () => {
    const { demo, snap } = await fresh();
    const p = snap.picks.find((x) => x.character_slug === 'biscuit')!;
    await expect(demo.decidePick(p.id, 'approve', null, null, { ownerNote: 'x'.repeat(281) })).rejects.toThrow(/280/);
    await expect(demo.decidePick(p.id, 'approve', null, null, { ownerMode: 'star' as never })).rejects.toThrow(/owner_mode/);
    await expect(demo.decidePick(p.id, 'approve', null, null, { ownerMode: 'dropin', ownerPresence: 'lead' as never })).rejects.toThrow(/owner_presence/);
    await expect(demo.decidePick(p.id, 'approve', null, 'biscuit', { alsoCharacter: 'biscuit' })).rejects.toThrow(/different/);
    await expect(demo.decidePick(p.id, 'approve', null, 'biscuit', { alsoCharacter: 'nobody' })).rejects.toThrow(/unknown character/);
    await expect(demo.decidePick(p.id, 'skip', 'no', null, { alsoCharacter: 'reginald' })).rejects.toThrow(/approving/);
    expect((await demo.load()).picks.some((x) => x.id === p.id)).toBe(true); // still waiting
  });

  it('serves every stage of the pipeline for both characters, and a finished scan', async () => {
    const { snap } = await fresh();
    // the roster of 2026-10-06 in the owner's order, Biscuit (retired, with his history) last
    expect(snap.characters.map((c) => [c.slug, c.status])).toEqual([
      ['franz', 'designing'], ['reginald', 'live'], ['lenny', 'designing'], ['biscuit', 'paused'],
    ]);
    expect(snap.characters.find((c) => c.slug === 'lenny')!.setup.planned_handles?.instagram).toBe('lennygold.agent');
    for (const slug of ['biscuit', 'reginald']) {
      const p = pipelineFor(slug, snap);
      expect([p.proposed.total, p.production.total, p.waiting.total, p.posted.total].map((n) => n > 0)).toEqual([true, true, true, true]);
    }
    const s = scannerStatus(snap.runs, NOW_MS);
    expect(s.state).toBe('finished');
    expect(s.last?.scan.picks_added).toBeGreaterThan(0);
    expect(s.creditsMonth).toBeGreaterThan(0);
    const b = goLiveChecklist(snap.characters.find((c) => c.slug === 'reginald')!);
    expect(b.items.every((i) => i.done)).toBe(true);
    expect(goLiveChecklist(snap.characters.find((c) => c.slug === 'franz')!).ready).toBe(false); // no accounts yet
  });
});
