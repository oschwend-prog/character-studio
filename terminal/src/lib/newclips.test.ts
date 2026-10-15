// New clips (owner 2026-10-15): where each clip came from, the folder row, the filtered list of clips available to make, and the
// production line. Pure functions over v_tracker rows; no browser.
import { describe, expect, it } from 'vitest';
import { availableClips, clipSource, folderStatus, parseAvailableFilter, productionCounts } from './newclips';
import type { DropCard, DropState, TrackerRow } from './types';

const NOW = Date.parse('2026-10-15T13:00:00Z');
const ago = (h: number) => new Date(NOW - h * 3_600_000).toISOString();
const card = (state: DropState, over: Partial<DropCard> = {}): DropCard => ({
  state, kind: 'file', at: ago(1), credits: 100, character_by: 'owner', ...over,
});
let n = 0;
const row = (slug: string | null, drop: DropCard | null, over: Partial<TrackerRow> = {}): TrackerRow => {
  n += 1;
  return {
    pick_id: `p${n}`, character_slug: slug, character_name: slug, url: `owner-drop:${n}`, drop_card: drop, approved_at: ago(1),
    clip_state: null, clip_id: null, status: 'approved', decision: null, ...over,
  } as unknown as TrackerRow;
};
const CAST = [{ slug: 'franz', name: 'Franz' }, { slug: 'reginald', name: 'Reginald' }];

describe('clipSource', () => {
  it('tells the folder, the scan, a link and an upload apart', () => {
    expect(clipSource(row('franz', card('ready', { folder_hash: 'abc' })))).toBe('folder');
    expect(clipSource(row('franz', card('ready', { kind: 'link', trend_stage: 'rising' })))).toBe('scan');
    expect(clipSource(row('franz', card('ready', { kind: 'link' }), { url: 'https://t.co/x' }), new Set(['https://t.co/x']))).toBe('scan');
    expect(clipSource(row('franz', card('ready', { kind: 'link' })))).toBe('link');
    expect(clipSource(row('franz', card('ready')))).toBe('upload');
  });
});

describe('folderStatus', () => {
  it('says when the newest folder clip came and how many came this week', () => {
    const rows = [
      row('franz', card('ready', { folder_hash: 'a' }), { approved_at: ago(2) }),
      row('franz', card('made', { folder_hash: 'b' }), { approved_at: ago(24 * 9) }),
      row('franz', card('ready'), { approved_at: ago(0.5) }),
    ];
    expect(folderStatus(rows, NOW)).toEqual({ newest: ago(2), week: 1 });
    expect(folderStatus([], NOW)).toEqual({ newest: null, week: 0 });
  });
});

describe('availableClips', () => {
  const rows = [
    row('franz', card('ready', { score: { total: 60 } as DropCard['score'] })),
    row('reginald', card('ready', { score: { total: 90 } as DropCard['score'] })),
    row('reginald', card('checking')),
    row('reginald', card('making')),
    row('reginald', card('made')),
    row('franz', card('blocked', { reason: 'a watermark' })),
  ];
  it('lists only what is not made yet, ready best first across characters', () => {
    const a = availableClips(rows, CAST, 'all');
    expect(a.ready.map((r) => r.character_slug)).toEqual(['reginald', 'franz']);
    expect(a.checking).toHaveLength(1);
    expect(a.problems).toHaveLength(1);
    expect(a.counts).toMatchObject({ all: 2, needs: 0, franz: 1, reginald: 1 });
  });
  it('filters to one character, or to the clips that need a character', () => {
    expect(availableClips(rows, CAST, 'franz').ready.map((r) => r.character_slug)).toEqual(['franz']);
    const needs = availableClips(rows, CAST, 'needs');
    expect(needs.ready).toEqual([]);
    expect(needs.checking).toEqual([]);
  });
  it('reads an unknown filter as All', () => {
    expect(parseAvailableFilter('lenny', ['franz'])).toBe('all');
    expect(parseAvailableFilter('needs', ['franz'])).toBe('needs');
    expect(parseAvailableFilter('franz', ['franz'])).toBe('franz');
  });
});

describe('productionCounts', () => {
  it('counts what is being made and what waits for his OK', () => {
    const rows = [row('reginald', card('making')), row('franz', card('made'), { clip_state: 'awaiting_approval', clip_id: 'c1' }), row('franz', card('ready'))];
    expect(productionCounts(rows)).toEqual({ making: 1, toApprove: 1 });
  });
});
