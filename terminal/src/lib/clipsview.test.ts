// Clips by character (spec section 6): the sections, the Top pick badge, the versions line, the folded line, the view switch.
import { describe, expect, it } from 'vitest';
import { cantUseLine, clipsByCharacter, clipsViewQuery, isTopPick, parseClipsView, sectionSummary, versionsLine } from './clipsview';
import type { DropCard, DropState, TrackerRow } from './types';

const NOW = Date.parse('2026-10-08T12:00:00+01:00');
const ago = (h: number) => new Date(NOW - h * 3_600_000).toISOString();
const card = (state: DropState, over: Partial<DropCard> = {}): DropCard => ({
  state, kind: 'file', at: ago(1), character_by: 'owner', window: { start_s: 0, length_s: 8 }, credits: 91,
  star: { kind: 'person', body: 'biped', description: 'a dancer', x_center: 0.5 }, ...over,
});
let n = 0;
const row = (slug: string | null, drop: DropCard | null, over: Partial<TrackerRow> = {}): TrackerRow => {
  n += 1;
  return {
    pick_id: `pick-${String(n).padStart(2, '0')}`, character_slug: slug, character_name: slug, url: `owner-drop:${n}`, platform: 'drop',
    creator_handle: null, views: null, outlier_x: null, tier: null, theme: null, concept: null, hook: null, thumbnail_url: null,
    preview_url: null, gallery: false, posted_at: null, velocity: null, proposed_mode: null, owner_mode: null, owner_presence: null,
    owner_music: null, owner_clip_path: null, status: 'approved', decision: null, approved_at: ago(2), note: null, source_id: null,
    analysis: null, fetch_failed: null, clip_id: null, clip_state: null, clip_mode: null, clip_state_since: null, clip_failure: null,
    credits_spent: 0, post_id: null, post_status: null, post_scheduled_for: null, post_posted_at: null, post_url: null, post_error: null,
    latest_views: null, caption: null, hashtags: null, first_comment: null, drop_card: drop, make_requested_at: null,
    ...over,
  };
};
const score = (total: number) => ({ total, potential: 7, swap: 8, reason: `scored ${total}` });
const LIVE = [{ slug: 'franz', name: 'Franz' }, { slug: 'reginald', name: 'Reginald' }];

describe('parseClipsView and clipsViewQuery', () => {
  it('opens By character by default; v=all or any filter is All clips', () => {
    expect(parseClipsView('')).toBe('character');
    expect(parseClipsView('c=franz')).toBe('character');
    expect(parseClipsView('v=all')).toBe('all');
    expect(parseClipsView('f=problems')).toBe('all'); // Today's Health link and old bookmarks
    expect(parseClipsView('v=other')).toBe('character');
  });
  it('writes the view into the query, keeping the other keys; By character drops the filter', () => {
    expect(clipsViewQuery('', 'all')).toBe('v=all');
    expect(clipsViewQuery('f=ready', 'all')).toBe('f=ready&v=all');
    expect(clipsViewQuery('v=all&f=ready&c=franz', 'character')).toBe('c=franz');
    expect(clipsViewQuery('', 'character')).toBe('');
  });
});

describe('clipsByCharacter', () => {
  const unscoredNew = row('franz', card('ready', { at: ago(0.5) }));
  const unscoredOld = row('franz', card('ready', { at: ago(30) }));
  const s90 = row('franz', card('ready', { score: score(90), at: ago(20) }));
  const s70 = row('franz', card('ready', { score: score(70), at: ago(3) }));
  const pick = row('franz', card('ready', { character_by: 'studio' }));
  const checking = row('franz', card('checking', { at: ago(0.2) }));
  const making = row('franz', card('making', { at: ago(5) }));
  const made = row('franz', card('made'));
  const blocked = row('franz', card('blocked', { reason: 'the star is a child' }));
  const failed = row('franz', card('failed', { reason: 'the job failed' }));
  const reginald = row('reginald', card('ready', { score: score(80) }));
  const biscuit = row('biscuit', card('ready'));
  const none = row(null, card('checking'));
  const scan = row('franz', null); // a scan pick: no drop card, not a clip
  const rows = [unscoredNew, unscoredOld, s90, s70, pick, checking, making, made, blocked, failed, reginald, biscuit, none, scan];

  it('gives each live character Needs you, his ranked Ready clips, what is on its way, done and the problems', () => {
    const { groups } = clipsByCharacter(rows, LIVE);
    const franz = groups[0];
    expect(groups.map((g) => g.slug)).toEqual(['franz', 'reginald']);
    expect(franz.needsYou).toEqual([pick]);
    // scored first by score, then the unscored newest first (Review Focus 3: no crash, no NaN)
    expect(franz.ready).toEqual([s90, s70, unscoredNew, unscoredOld]);
    expect(franz.onTheWay).toEqual([checking, making]);
    expect(franz.done).toEqual([made]);
    expect(franz.problems.map((r) => r.drop_card!.state).sort()).toEqual(['blocked', 'failed']);
    expect(groups[1].ready).toEqual([reginald]);
  });

  it('leaves the clips of no live character to All clips, and never lists a scan pick', () => {
    const { groups, others } = clipsByCharacter(rows, LIVE);
    expect(others).toEqual([biscuit, none]);
    expect(groups.flatMap((g) => [...g.needsYou, ...g.ready, ...g.onTheWay, ...g.done, ...g.problems])).not.toContain(scan);
  });

  it('gives the Top pick badge to the first three ranked clips that have a score', () => {
    const { ready } = clipsByCharacter(rows, LIVE).groups[0];
    expect(ready.map((r, i) => isTopPick(r, i))).toEqual([true, true, false, false]);
    expect(isTopPick(s90, 3)).toBe(false);
    expect(isTopPick(s90, -1)).toBe(false);
  });

  it('says his counts in one line', () => {
    const { groups } = clipsByCharacter(rows, LIVE);
    expect(sectionSummary(groups[0])).toBe('4 ready · 1 needs your choice · 2 on their way · 1 done');
    expect(sectionSummary(groups[1])).toBe('1 ready');
    expect(sectionSummary({ ...groups[1], ready: [] })).toBe('nothing yet');
    expect(sectionSummary({ ...groups[1], ready: [], problems: [blocked] })).toBe('nothing usable yet');
  });
});

describe('versionsLine and the folded line', () => {
  it('names the other members of the clip family with their status, from the root or a version', () => {
    const root = row('reginald', card('ready', { score: score(80) }));
    const lenny = row('lenny', card('checking', { copy_of: root.pick_id, at: ago(0.5) }));
    const skipped = row('franz', card('ready', { copy_of: root.pick_id }), { status: 'skipped' });
    const rows = [root, lenny, skipped];
    const names = new Map([['lenny', 'Lenny Gold']]);
    expect(versionsLine(root, rows, names)).toBe('Also: Lenny Gold, being checked');
    expect(versionsLine(lenny, rows, names)).toBe('Also: Reginald, ready');
    expect(versionsLine(row('franz', card('ready')), rows)).toBeNull();
    const studioRoot = row('reginald', card('ready', { character_by: 'studio' }));
    const version = row('lenny', card('ready', { copy_of: studioRoot.pick_id }));
    expect(versionsLine(version, [studioRoot, version])).toBe('Also: Reginald, waits for your choice');
  });
  it('folds the blocked and failed clips into one line', () => {
    expect(cantUseLine(1)).toBe('1 clip can’t be used: see why');
    expect(cantUseLine(3)).toBe('3 clips can’t be used: see why');
  });
});
