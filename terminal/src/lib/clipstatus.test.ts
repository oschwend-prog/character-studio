// Terminal v2, Clips page: one chip per dropped clip (Adding, Checking, Pick a character, Ready, Making, Done, Blocked, Failed) and
// the filters over them. Pure functions over v_tracker rows; no browser.
import { describe, expect, it } from 'vitest';
import {
  CHIP_CLASS, CHIP_LABEL, CLIP_FILTERS, CLIP_FILTER_EMPTY, characterConfirm, clipActions, clipChip, clipFilterQuery, filterClips, makeTotal,
  newestFirst, parseClipFilter,
  type ClipChip, type ClipFilter,
} from './clipstatus';
import type { ClipState, DropCard, DropState, TrackerRow } from './types';

const NOW = Date.parse('2026-10-07T12:00:00Z');
const ago = (m: number) => new Date(NOW - m * 60_000).toISOString();

const card = (state: DropState, over: Partial<DropCard> = {}): DropCard => ({ state, kind: 'file', at: ago(5), ...over });

let n = 0;
const row = (drop: DropCard | null, over: Partial<TrackerRow> = {}): TrackerRow => {
  n += 1;
  return {
    pick_id: `pick-${String(n).padStart(3, '0')}`, character_slug: 'reginald', character_name: 'Reginald', url: `owner-drop:${n}`, platform: 'drop',
    creator_handle: null, views: null, outlier_x: null, tier: null, theme: null, concept: null, hook: null, thumbnail_url: null,
    preview_url: null, gallery: false, posted_at: null, velocity: null, proposed_mode: null, owner_mode: null, owner_presence: null,
    owner_music: null, owner_clip_path: null, status: 'approved', decision: { decision: 'approve', by: 'owner', reason: "owner's own video" },
    approved_at: ago(10), note: null, source_id: null, analysis: null, fetch_failed: null, clip_id: null, clip_state: null, clip_mode: null,
    clip_state_since: null, clip_failure: null, credits_spent: 0, post_id: null, post_status: null, post_scheduled_for: null,
    post_posted_at: null, post_url: null, post_error: null, latest_views: null, caption: null, hashtags: null, first_comment: null,
    drop_card: drop, make_requested_at: null,
    ...over,
  };
};
const withClip = (drop: DropCard | null, clip_state: ClipState, over: Partial<TrackerRow> = {}) =>
  row(drop, { clip_id: `clip-${n + 1}`, clip_state, clip_mode: 'dropin', clip_state_since: ago(3), ...over });

describe('clipChip: one chip per rule', () => {
  it('uploading is Adding', () => {
    expect(clipChip(row(card('uploading')))).toBe('adding');
  });

  it('checking and waiting are Checking', () => {
    expect(clipChip(row(card('checking')))).toBe('checking');
    expect(clipChip(row(card('waiting')))).toBe('checking');
  });

  it('ready with a character the studio chose is Pick a character; the owner’s own choice is Ready', () => {
    expect(clipChip(row(card('ready', { character_by: 'studio' })))).toBe('pick');
    expect(clipChip(row(card('ready', { character_by: 'owner' })))).toBe('ready');
    // a drop from before migration 0013 has no character_by: the studio set its character, so it is not chosen yet (a paid Make it needs his tap)
    expect(clipChip(row(card('ready')))).toBe('pick');
  });

  it('making: the drop is making, or Make it was tapped and no clip exists yet, or its clip is between planned and mastered', () => {
    expect(clipChip(row(card('making')))).toBe('making');
    expect(clipChip(row(card('ready', { character_by: 'owner' }), { make_requested_at: ago(1) }))).toBe('making');
    const states: ClipState[] = ['planned', 'generating', 'gen_failed', 'generated', 'qa_failed', 'qa_passed', 'mastered'];
    for (const s of states) expect([s, clipChip(withClip(card('making'), s))]).toEqual([s, 'making']);
    expect(clipChip(withClip(card('ready', { character_by: 'owner' }), 'generating'))).toBe('making'); // the drop card lags behind its clip
    expect(clipChip(withClip(card('ready', { character_by: 'owner' }), 'planned', { make_requested_at: ago(1) }))).toBe('making');
  });

  it('done: made, or its clip reached the owner’s OK or later', () => {
    expect(clipChip(row(card('made')))).toBe('done');
    for (const s of ['awaiting_approval', 'approved', 'scheduled', 'posted'] as ClipState[]) {
      expect([s, clipChip(withClip(card('making'), s))]).toEqual([s, 'done']);
    }
    expect(clipChip(withClip(card('made'), 'awaiting_approval', { status: 'made' }))).toBe('done');
  });

  it('a rejected or dropped clip is done only when the drop is made; otherwise the drop state decides', () => {
    expect(clipChip(withClip(card('made'), 'rejected', { status: 'made' }))).toBe('done');
    expect(clipChip(withClip(card('made'), 'dropped', { status: 'made' }))).toBe('done');
    expect(clipChip(withClip(card('making'), 'rejected'))).toBe('making');
    expect(clipChip(withClip(card('failed'), 'dropped'))).toBe('failed');
    expect(clipChip(withClip(card('blocked'), 'rejected'))).toBe('blocked');
  });

  it('blocked is Blocked', () => {
    expect(clipChip(row(card('blocked')))).toBe('blocked');
  });

  it('failed is Failed, even after Make it was tapped (Try again is offered) or with a half-made clip', () => {
    expect(clipChip(row(card('failed')))).toBe('failed');
    expect(clipChip(row(card('failed', { credits: 91 }), { make_requested_at: ago(30) }))).toBe('failed');
    expect(clipChip(withClip(card('failed'), 'gen_failed'))).toBe('failed');
  });

  it('a row without a drop card (a scan pick) follows its clip alone, else it is still being checked', () => {
    expect(clipChip(row(null))).toBe('checking');
    expect(clipChip(withClip(null, 'generating'))).toBe('making');
    expect(clipChip(row(null, { make_requested_at: ago(1) }))).toBe('making');
    expect(clipChip(withClip(null, 'scheduled', { status: 'made' }))).toBe('done');
  });

  it('has a label for every chip, in the owner’s words', () => {
    expect(CHIP_LABEL).toEqual({
      adding: 'Adding', checking: 'Checking', pick: 'Pick a character', ready: 'Ready', making: 'Making', done: 'Done', blocked: 'Blocked', failed: 'Failed',
    });
    const chips: ClipChip[] = ['adding', 'checking', 'pick', 'ready', 'making', 'done', 'blocked', 'failed'];
    expect(Object.keys(CHIP_LABEL).sort()).toEqual([...chips].sort());
  });
});

describe('filterClips', () => {
  const all = {
    adding: row(card('uploading')),
    checking: row(card('checking')),
    pick: row(card('ready', { character_by: 'studio' })),
    ready: row(card('ready', { character_by: 'owner' })),
    making: row(card('making')),
    done: row(card('made')),
    blocked: row(card('blocked')),
    failed: row(card('failed')),
  };
  const scan = row(null, { status: 'queued' }); // a scan pick has no card: it never shows on the Clips page
  const rows = [...Object.values(all), scan];
  const ids = (f: ClipFilter) => filterClips(rows, f).map((r) => r.pick_id);

  it('all keeps every clip with a drop card, in the order given', () => {
    expect(ids('all')).toEqual(Object.values(all).map((r) => r.pick_id));
  });

  it('pick, ready, making and done each keep their own chip', () => {
    expect(ids('pick')).toEqual([all.pick.pick_id]);
    expect(ids('ready')).toEqual([all.ready.pick_id]);
    expect(ids('making')).toEqual([all.making.pick_id]);
    expect(ids('done')).toEqual([all.done.pick_id]);
  });

  it('problems are the blocked and the failed', () => {
    expect(ids('problems')).toEqual([all.blocked.pick_id, all.failed.pick_id]);
  });

  it('an empty list stays empty', () => {
    for (const f of ['all', 'pick', 'ready', 'making', 'done', 'problems'] as ClipFilter[]) expect(filterClips([], f)).toEqual([]);
  });
});

describe('the filter row and its address', () => {
  it('lists the filters in the owner’s words, one per ClipFilter, All first', () => {
    expect(CLIP_FILTERS.map((o) => o.label)).toEqual(['All', 'Pick a character', 'Ready', 'Making', 'Done', 'Blocked or failed']);
    expect(CLIP_FILTERS.map((o) => o.id)).toEqual(['all', 'pick', 'ready', 'making', 'done', 'problems']);
    // the chips of the filters that are one chip say the chip's own label
    for (const o of CLIP_FILTERS.filter((x) => x.id in CHIP_LABEL)) expect(o.label).toBe(CHIP_LABEL[o.id as ClipChip]);
  });

  it('has a one-line empty state for every filter', () => {
    expect(Object.keys(CLIP_FILTER_EMPTY).sort()).toEqual(CLIP_FILTERS.map((o) => o.id).sort());
    for (const line of Object.values(CLIP_FILTER_EMPTY)) {
      expect(line.trim()).not.toBe('');
      expect(line).not.toMatch(/\n/);
    }
    expect(CLIP_FILTER_EMPTY.pick).toBe('No clips wait for a character.');
  });

  it('reads ?f= from the query of the hash (Today’s tile and warning links), an unknown or missing f is All', () => {
    expect(parseClipFilter('f=pick')).toBe('pick');
    expect(parseClipFilter('f=ready')).toBe('ready');
    expect(parseClipFilter('f=problems')).toBe('problems');
    expect(parseClipFilter('?f=done')).toBe('done');
    expect(parseClipFilter('c=franz&f=making')).toBe('making');
    expect(parseClipFilter('')).toBe('all');
    expect(parseClipFilter('f=')).toBe('all');
    expect(parseClipFilter('f=nonsense')).toBe('all');
    expect(parseClipFilter('f=READY')).toBe('all');
    expect(parseClipFilter('f=toString')).toBe('all');
    expect(parseClipFilter('f=__proto__')).toBe('all');
    expect(parseClipFilter('g=ready')).toBe('all');
  });

  it('writes the filter back and keeps every other key of the query; All leaves a clean address', () => {
    expect(clipFilterQuery('', 'ready')).toBe('f=ready');
    expect(clipFilterQuery('f=pick', 'done')).toBe('f=done');
    expect(clipFilterQuery('c=franz&f=pick', 'done')).toBe('c=franz&f=done');
    expect(clipFilterQuery('c=franz', 'problems')).toBe('c=franz&f=problems');
    expect(clipFilterQuery('f=pick', 'all')).toBe('');
    expect(clipFilterQuery('c=franz&f=pick', 'all')).toBe('c=franz');
    expect(clipFilterQuery('', 'all')).toBe('');
    // a round trip: what is written is what is read
    for (const o of CLIP_FILTERS) expect(parseClipFilter(clipFilterQuery('c=franz', o.id))).toBe(o.id);
  });
});

describe('the status cell’s look and the buttons of a row', () => {
  it('maps every chip onto an existing .drop-state class: Pick a character looks like Ready, Done like Made, Adding like Uploading', () => {
    expect(CHIP_CLASS).toEqual({
      adding: 'uploading', checking: 'checking', pick: 'ready', ready: 'ready', making: 'making', done: 'made', blocked: 'blocked', failed: 'failed',
    });
    expect(Object.keys(CHIP_CLASS).sort()).toEqual(Object.keys(CHIP_LABEL).sort());
  });

  it('a ready clip offers Make it and Adjust; a blocked one Remove; a failed one Try again, Adjust and Remove', () => {
    expect(clipActions(row(card('ready', { character_by: 'owner' })), NOW)).toEqual(['make', 'adjust']);
    expect(clipActions(row(card('ready', { character_by: 'studio' })), NOW)).toEqual(['make', 'adjust']); // Pick a character: Make it confirms it
    expect(clipActions(row(card('blocked')), NOW)).toEqual(['remove']);
    expect(clipActions(row(card('failed', { credits: 91 })), NOW)).toEqual(['retry-make', 'adjust', 'remove']); // priced: Adjust it again too
    expect(clipActions(row(card('failed')), NOW)).toEqual(['retry-check', 'remove']);
    expect(clipActions(row(card('waiting')), NOW)).toEqual(['retry-check', 'remove']);
    expect(clipActions(row(card('checking')), NOW)).toEqual([]);
  });

  it('never offers a paid button next to a Making or Done chip (the drop card lags behind its clip)', () => {
    const lagging = card('ready', { character_by: 'owner' });
    expect(clipActions(row(lagging, { make_requested_at: ago(1) }), NOW)).toEqual([]); // Make it was tapped, no clip yet
    expect(clipActions(withClip(lagging, 'generating'), NOW)).toEqual([]);
    expect(clipActions(withClip(lagging, 'awaiting_approval', { status: 'made' }), NOW)).toEqual([]);
    expect(clipActions(row(card('making')), NOW)).toEqual([]);
    // Remove stays: a Done clip whose card failed can still be taken off the list
    expect(clipActions(withClip(card('failed', { credits: 91 }), 'awaiting_approval', { status: 'made' }), NOW)).toEqual(['remove']);
  });

  it('a stale upload offers Remove; a row without a drop card offers nothing', () => {
    expect(clipActions(row(card('uploading', { at: ago(45) })), NOW)).toEqual(['remove']);
    expect(clipActions(row(card('uploading')), NOW)).toEqual([]);
    expect(clipActions(row(null), NOW)).toEqual([]);
  });
});

describe('newestFirst: the Clips page lists the newest drop first, whatever its state', () => {
  const at = (m: number, state: DropState = 'ready', over: Partial<TrackerRow> = {}) => row(card(state, { at: ago(m) }), over);
  const ids = (rows: TrackerRow[]) => newestFirst(rows).map((r) => r.pick_id);

  it('sorts by the card’s time, newest first, and does not group by state', () => {
    const readyOld = at(300, 'ready');
    const madeNew = at(5, 'made');
    const failedMid = at(60, 'failed');
    const blockedNewer = at(20, 'blocked');
    expect(ids([readyOld, madeNew, failedMid, blockedNewer])).toEqual([madeNew, blockedNewer, failedMid, readyOld].map((r) => r.pick_id));
  });

  it('falls back to when the pick was approved when the card has no valid time', () => {
    const noAt = row({ state: 'ready', kind: 'file' } as DropCard, { approved_at: ago(30) });
    const badAt = row(card('ready', { at: 'not a time' }), { approved_at: ago(10) });
    const dated = at(20);
    // approved 10 min ago (bad card time), 20 min ago (card), 30 min ago (no card time)
    expect(ids([noAt, dated, badAt])).toEqual([badAt, dated, noAt].map((r) => r.pick_id));
  });

  it('puts a clip with neither time last, and breaks ties by pick id so the order is stable', () => {
    const none = row({ state: 'ready', kind: 'file' } as DropCard, { approved_at: 'never' });
    const empty = row(card('ready', { at: '' }), { approved_at: '' });
    const newer = at(1);
    const [a, b] = [at(10, 'ready', { pick_id: 'pick-a' }), at(10, 'checking', { pick_id: 'pick-b' })];
    b.drop_card = { ...b.drop_card!, at: a.drop_card!.at }; // exactly the same time
    expect(ids([none, b, empty, a, newer])).toEqual([newer.pick_id, 'pick-a', 'pick-b', ...[none, empty].map((r) => r.pick_id).sort()]);
    expect(ids([a, b, newer, none, empty])).toEqual(ids([none, empty, newer, b, a]));
  });

  it('returns a new list and leaves the input alone', () => {
    const rows = [at(50), at(10)];
    const before = rows.map((r) => r.pick_id);
    const sorted = newestFirst(rows);
    expect(sorted).not.toBe(rows);
    expect(rows.map((r) => r.pick_id)).toEqual(before);
    expect(newestFirst([])).toEqual([]);
  });
});

describe('makeTotal: the header line adds up what the owner can Make now', () => {
  const priced = (state: DropState, over: Partial<DropCard> = {}) =>
    card(state, { window: { start_s: 0, length_s: 9 }, credits: 102, seconds: 9, ...over });
  const OWNER = { character_by: 'owner' as const };
  const STUDIO = { character_by: 'studio' as const };

  it('counts the Ready and the Pick a character clips, each at its own price (102 credits for 9 s)', () => {
    expect(makeTotal([row(priced('ready', OWNER)), row(priced('ready', STUDIO))], NOW)).toEqual({ count: 2, credits: 204 });
  });

  it('uses the owner’s Adjust for the price, like the table', () => {
    const adjusted = row(priced('ready', { ...OWNER, adjust: { length_s: 6 } })); // 6 s: ceil(6 x 11) + 3 = 69
    expect(makeTotal([adjusted, row(priced('ready', OWNER))], NOW)).toEqual({ count: 2, credits: 69 + 102 });
  });

  it('leaves out what is Making or Done, even when its card still says ready', () => {
    const lagging = priced('ready', OWNER);
    const rows = [
      row(priced('making')),
      row(priced('made')),
      row(lagging, { make_requested_at: ago(1) }), // Make it was tapped, no clip yet
      withClip(lagging, 'generating'),
      withClip(lagging, 'awaiting_approval', { status: 'made' }),
    ];
    expect(makeTotal(rows, NOW)).toEqual({ count: 0, credits: 0 });
    // …and counts the one clip next to them that can still be made
    expect(makeTotal([...rows, row(priced('ready', OWNER))], NOW)).toEqual({ count: 1, credits: 102 });
  });

  it('leaves out clips that are checking, blocked or failed (Try again is not Make it), and rows without a card', () => {
    const rows = [
      row(card('uploading')), row(card('checking')), row(card('waiting')), row(card('blocked')),
      row(priced('failed')), row(priced('failed', { credits: undefined })), row(null),
    ];
    expect(makeTotal(rows, NOW)).toEqual({ count: 0, credits: 0 });
    expect(makeTotal([], NOW)).toEqual({ count: 0, credits: 0 });
  });

  it('agrees with the Ready filter plus the Pick a character filter, so the line and the chips tell one story', () => {
    const rows = [
      row(priced('ready', OWNER)), row(priced('ready', STUDIO)), row(priced('ready')), row(priced('making')), row(priced('made')),
      withClip(priced('ready', OWNER), 'generating'), row(card('checking')), row(priced('failed')),
    ];
    expect(makeTotal(rows, NOW).count).toBe(filterClips(rows, 'ready').length + filterClips(rows, 'pick').length);
  });
});

describe('"Pick a character" can be cleared with one free tap (final review)', () => {
  const ROSTER = [{ slug: 'franz', name: 'Franz' }, { slug: 'reginald', name: 'Reginald' }, { slug: 'lenny', name: 'Lenny Gold' }];

  it('offers "Use <him>" while the studio chose the character (or nobody recorded it) on a ready clip', () => {
    expect(characterConfirm(row(card('ready', { character_by: 'studio' })), ROSTER)).toEqual({ slug: 'reginald', name: 'Reginald' });
    // a drop from before migration 0013 has no character_by: the chip says Pick a character, so the tap must be there too
    const legacy = row(card('ready'), { character_slug: 'lenny' });
    expect(clipChip(legacy)).toBe('pick');
    expect(characterConfirm(legacy, ROSTER)).toEqual({ slug: 'lenny', name: 'Lenny Gold' });
  });

  it('offers it exactly when the chip is Pick a character: never for his own choice, nor while checking, making, blocked, failed or done', () => {
    expect(characterConfirm(row(card('ready', { character_by: 'owner' })), ROSTER)).toBeNull();
    for (const state of ['uploading', 'checking', 'waiting', 'blocked', 'failed', 'making', 'made'] as DropState[]) {
      expect([state, characterConfirm(row(card(state, { character_by: 'studio' })), ROSTER)]).toEqual([state, null]);
    }
    const lagging = row(card('ready', { character_by: 'studio' }), { make_requested_at: ago(1) }); // Make it was tapped: Making
    expect(clipChip(lagging)).toBe('making');
    expect(characterConfirm(lagging, ROSTER)).toBeNull();
    expect(characterConfirm(withClip(card('ready', { character_by: 'studio' }), 'generating', { status: 'queued' }), ROSTER)).toBeNull();
    expect(characterConfirm(row(null), ROSTER)).toBeNull(); // a scan pick
  });

  it('is not offered for a character who is no longer offered (paused: set_drop_character refuses him), the menu does the choosing then', () => {
    const paused = row(card('ready'), { character_slug: 'biscuit' });
    expect(clipChip(paused)).toBe('pick');
    expect(characterConfirm(paused, ROSTER)).toBeNull();
    expect(characterConfirm(row(card('ready'), { character_slug: null }), ROSTER)).toBeNull();
  });

  it('the demo: one tap on a seeded Pick a character clip makes it Ready and records it as his choice', async () => {
    const { DemoBackend } = await import('../demo/backend');
    const demo = new DemoBackend(() => NOW);
    const snap = await demo.load();
    const waiting = snap.tracker.filter((r) => clipChip(r) === 'pick' && characterConfirm(r, ROSTER));
    expect(waiting.length).toBeGreaterThanOrEqual(2); // a studio-chosen one and a legacy one (no character_by)
    expect(waiting.some((r) => r.drop_card?.character_by === 'studio') && waiting.some((r) => r.drop_card?.character_by === undefined)).toBe(true);
    for (const r of waiting) {
      const confirm = characterConfirm(r, ROSTER)!;
      expect(await demo.setDropCharacter(r.pick_id, confirm.slug)).toEqual({ dispatched: false }); // only records it: nothing is checked again
      const after = (await demo.load()).tracker.find((x) => x.pick_id === r.pick_id)!;
      expect(after.character_slug).toBe(confirm.slug); // the same character stays
      expect(after.drop_card).toMatchObject({ state: 'ready', character_by: 'owner' });
      expect(clipChip(after)).toBe('ready');
      expect(characterConfirm(after, ROSTER)).toBeNull();
      expect(after.drop_card?.credits).toBe(r.drop_card?.credits); // the price stays: no new check
    }
  });
});
