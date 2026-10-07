// Terminal v2, Clips page: one chip per dropped clip (Adding, Checking, Pick a character, Ready, Making, Done, Blocked, Failed) and
// the filters over them. Pure functions over v_tracker rows; no browser.
import { describe, expect, it } from 'vitest';
import { CHIP_LABEL, clipChip, filterClips, type ClipChip, type ClipFilter } from './clipstatus';
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
