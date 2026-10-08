// Terminal v3 (spec sections 4-6): the clips ranked by their score, the top picks, who else may take a clip, the price of a
// selection and "Make N selected" one by one. Pure functions over v_tracker rows; no browser.
import { describe, expect, it } from 'vitest';
import { dropCredits } from './drop';
import {
  MAX_FAMILY, familyOf, familyRootId, makeMany, makeSummary, rankClips, reuseTargets, scoreOf, selectionTotal, topPicks,
} from './ranking';
import type { Character, DropAdjust, DropCard, DropScore, DropState, TrackerRow } from './types';

const NOW = Date.parse('2026-10-08T12:00:00Z');
const HOUR = 3_600_000;
const ago = (h: number) => new Date(NOW - h * HOUR).toISOString();

const score = (total: number): DropScore => ({ total, potential: Math.round(total / 10), swap: 8, reason: `scored ${total}` });
/** A checked, priced drop of the owner's character (an 8 s section of the clip's own sound: 91 credits). */
const card = (state: DropState, over: Partial<DropCard> = {}): DropCard => ({
  state, kind: 'file', at: ago(1), character_by: 'owner', source_id: 'src-1', window: { start_s: 0, length_s: 8 }, seconds: 8, credits: 91,
  star: { kind: 'person', body: 'biped', description: 'the man in the middle', x_center: 0.5, full_body: true },
  ...over,
});

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
const ids = (rows: ReadonlyArray<TrackerRow>) => rows.map((r) => r.pick_id);

describe('scoreOf', () => {
  it('reads the total of a score, and nothing from a clip checked before the score existed (Review Focus 3)', () => {
    expect(scoreOf(row(card('ready', { score: score(88) })))).toBe(88);
    expect(scoreOf(row(card('ready', { score: score(0) })))).toBe(0); // a score of 0 is a score
    for (const bad of [undefined, null, {}, { total: null }, { total: 'abc' }, { total: Number.NaN }, { total: Infinity }, 'x']) {
      expect(scoreOf(row(card('ready', { score: bad as never })))).toBeNull();
    }
    expect(scoreOf(row(null))).toBeNull();
  });
});

describe('rankClips', () => {
  it('puts the scored clips first by score, highest first, then the unscored ones newest first', () => {
    const low = row(card('ready', { score: score(55), at: ago(1) }));
    const top = row(card('ready', { score: score(91), at: ago(9) }));
    const oldUnscored = row(card('ready', { at: ago(30) }));
    const newUnscored = row(card('ready', { at: ago(2) }));
    const mid = row(card('ready', { score: score(72), at: ago(5) }));
    expect(ids(rankClips([low, oldUnscored, top, newUnscored, mid]))).toEqual(ids([top, mid, low, newUnscored, oldUnscored]));
  });

  it('breaks a tie on the score with the newest clip, then the pick id, so the order never jumps', () => {
    const older = row(card('ready', { score: score(80), at: ago(10) }));
    const newer = row(card('ready', { score: score(80), at: ago(1) }));
    const sameA = row(card('ready', { score: score(80), at: ago(20) }), { pick_id: 'pick-a' });
    const sameB = row(card('ready', { score: score(80), at: ago(20) }), { pick_id: 'pick-b' });
    expect(ids(rankClips([sameB, older, sameA, newer]))).toEqual([newer.pick_id, older.pick_id, 'pick-a', 'pick-b']);
  });

  it('dates a clip by its card, else by its approval, and puts one with no valid time last among the unscored', () => {
    const noCardTime = row(card('ready', { at: undefined }), { approved_at: ago(3) });
    const recent = row(card('ready', { at: ago(1) }));
    const timeless = row(card('ready', { at: 'not a time' }), { approved_at: 'never' });
    expect(ids(rankClips([timeless, noCardTime, recent]))).toEqual(ids([recent, noCardTime, timeless]));
  });

  it('never crashes or sorts by NaN on a malformed score, and returns a new list', () => {
    const scored = row(card('ready', { score: score(60) }));
    const broken = row(card('ready', { score: { total: 'n/a' } as never, at: ago(1) }));
    const empty = row(card('ready', { score: null, at: ago(4) }));
    const input = [empty, broken, scored];
    const out = rankClips(input);
    expect(ids(out)).toEqual(ids([scored, broken, empty]));
    expect(ids(input)).toEqual(ids([empty, broken, scored])); // untouched
  });
});

describe('topPicks', () => {
  it('is the 3 best Ready clips of the owner’s character (a score first), never one being made, blocked or still his to choose', () => {
    const r = [
      row(card('ready', { score: score(70) })),
      row(card('ready', { score: score(95) })),
      row(card('ready', { at: ago(1) })), // unscored: after the scored ones
      row(card('ready', { score: score(80) })),
      row(card('ready', { score: score(99), character_by: 'studio' })), // the studio chose him: Needs you, not a top pick
      row(card('ready', { score: score(98) }), { make_requested_at: ago(1) }), // Make it already tapped: Making
      row(card('making', { score: score(97) })),
      row(card('blocked', { score: undefined })),
      row(card('made', { score: score(96) }), { clip_id: 'c', clip_state: 'awaiting_approval' }),
    ];
    expect(ids(topPicks(r))).toEqual(ids([r[1], r[3], r[0]]));
    expect(ids(topPicks(r, 1))).toEqual(ids([r[1]]));
    expect(ids(topPicks(r, 10))).toEqual(ids([r[1], r[3], r[0], r[2]])); // fewer than n: all of them
    expect(topPicks([])).toEqual([]);
  });
});

// ---- reuse: one clip, up to three characters (spec section 4) -------------------------------------------------------------------

const character = (slug: string, name: string, over: Partial<Character> = {}): Character => ({
  slug, name, status: 'live', bodies: ['biped'], setup: { stars: ['person'] }, accounts: [], ...over,
});
const ROSTER: Character[] = [
  character('biscuit', 'Biscuit', { status: 'paused', bodies: ['biped', 'quadruped'], setup: { stars: ['dog', 'animal'] } }),
  character('borat', 'Borat Type', { status: 'designing', setup: {} }), // seeded before terminal v3: no stars list, only bodies
  character('lenny', 'Lenny Gold'),
  character('reginald', 'Reginald'),
  character('franz', 'Franz', { bodies: ['biped', 'quadruped'], setup: { stars: ['dog', 'person'] } }),
];
const slugs = (list: ReadonlyArray<{ slug: string }>) => list.map((c) => c.slug);
const version = (root: TrackerRow, slug: string, state: DropState = 'checking', over: Partial<TrackerRow> = {}) =>
  row(card(state, { copy_of: root.pick_id }), { character_slug: slug, ...over });

describe('the family of a clip', () => {
  it('is the root and its versions: a version (of a version too) points at the root, the root first', () => {
    const root = row(card('ready'));
    const v1 = version(root, 'lenny');
    const v2 = version(root, 'franz');
    const other = row(card('ready'));
    expect(familyRootId(root)).toBe(root.pick_id);
    expect(familyRootId(v1)).toBe(root.pick_id);
    expect(familyRootId(row(card('ready', { copy_of: '' })))).not.toBe(''); // a malformed copy_of finds no root: itself
    expect(ids(familyOf(v2, [other, v2, v1, root]))).toEqual(ids([root, v1, v2])); // then the versions, oldest first
    expect(ids(familyOf(other, [other, v2, v1, root]))).toEqual(ids([other]));
    expect(familyOf(row(null), [root])).toEqual([]);
  });

  it('leaves out a skipped member', () => {
    const root = row(card('ready'));
    const skipped = version(root, 'lenny', 'ready', { status: 'skipped' });
    expect(ids(familyOf(root, [root, skipped]))).toEqual(ids([root]));
  });
});

describe('reuseTargets', () => {
  it('offers every character who replaces this kind of star, in the owner’s order, but not his own and not a paused one', () => {
    const root = row(card('ready'));
    expect(slugs(reuseTargets(root, ROSTER, [root]))).toEqual(['franz', 'lenny', 'borat']);
    expect(reuseTargets(root, ROSTER, [root])[0]).toEqual({ slug: 'franz', name: 'Franz' });
  });

  it('leaves out the characters the family already has, asked from the root or from a version', () => {
    const root = row(card('ready'));
    const lenny = version(root, 'lenny');
    expect(slugs(reuseTargets(root, ROSTER, [root, lenny]))).toEqual(['franz', 'borat']);
    expect(slugs(reuseTargets(lenny, ROSTER, [root, lenny]))).toEqual(['franz', 'borat']);
    // a skipped version frees its character again
    const skipped = version(root, 'lenny', 'ready', { status: 'skipped' });
    expect(slugs(reuseTargets(root, ROSTER, [root, skipped]))).toEqual(['franz', 'lenny', 'borat']);
  });

  it('stops at 3 members (a 4th never slips through)', () => {
    expect(MAX_FAMILY).toBe(3);
    const root = row(card('ready'));
    const family = [root, version(root, 'lenny'), version(root, 'franz')];
    for (const member of family) expect(reuseTargets(member, ROSTER, family)).toEqual([]);
  });

  it('is like for like: the star’s kind against who he replaces, and its body against his bodies; no stars list = the body alone', () => {
    const dog = row(card('ready', { star: { kind: 'dog', body: 'quadruped', description: 'the beagle', x_center: 0.5 } }), { character_slug: 'franz' });
    expect(reuseTargets(dog, ROSTER, [dog])).toEqual([]); // Reginald and Lenny replace a person; Borat has no four-legged body
    const upright = row(card('ready', { star: { kind: 'dog', body: 'biped', description: 'the dog on two legs', x_center: 0.5 } }), { character_slug: 'franz' });
    expect(slugs(reuseTargets(upright, ROSTER, [upright]))).toEqual(['borat']); // no stars list: allowed by his body, as the SQL does
    const swapKey = [...ROSTER.filter((c) => c.slug !== 'lenny'), character('lenny', 'Lenny Gold', { setup: { swap: { stars: ['dog'] } } })];
    expect(slugs(reuseTargets(upright, swapKey, [upright]))).toEqual(['lenny', 'borat']); // setup.swap.stars (the key 0013 read) counts too
    for (const star of [undefined, { kind: 'none', body: 'biped', description: 'nobody', x_center: 0.5 }] as DropCard['star'][]) {
      const r = row(card('ready', { star }));
      expect(reuseTargets(r, ROSTER, [r])).toEqual([]);
    }
  });

  it('needs the root checked: ready, making or made; nothing while it is checked again, blocked or failed, or not loaded', () => {
    for (const state of ['ready', 'making', 'made'] as DropState[]) {
      const root = row(card(state));
      expect([state, slugs(reuseTargets(root, ROSTER, [root]))]).toEqual([state, ['franz', 'lenny', 'borat']]);
    }
    for (const state of ['uploading', 'checking', 'waiting', 'blocked', 'failed'] as DropState[]) {
      const root = row(card(state));
      const v = version(root, 'lenny', 'ready');
      expect([state, reuseTargets(root, ROSTER, [root, v]), reuseTargets(v, ROSTER, [root, v])]).toEqual([state, [], []]);
    }
    const orphan = version(row(card('ready')), 'lenny', 'ready'); // its root is not among the rows: nothing can be checked
    expect(reuseTargets(orphan, ROSTER, [orphan])).toEqual([]);
    expect(reuseTargets(row(null), ROSTER, [])).toEqual([]);
  });
});

// ---- the selection bar (spec section 5.2) ---------------------------------------------------------------------------------------

describe('selectionTotal', () => {
  it('sums the price each ticked row shows (its own Adjust included), once per clip, only priced clips', () => {
    const eight = row(card('ready')); // 8 s: 91
    const twelve = row(card('ready', { window: { start_s: 0, length_s: 12 }, seconds: 12, credits: 135 }));
    const adjusted = row(card('ready', { adjust: { length_s: 12 } }));
    const unpriced = row(card('checking', { credits: undefined, window: undefined }));
    const rows = [eight, twelve, adjusted, unpriced];
    expect(dropCredits(twelve.drop_card!)).toBe(135);
    expect(selectionTotal(rows, [eight.pick_id, twelve.pick_id])).toEqual({ count: 2, credits: 91 + 135 });
    expect(selectionTotal(rows, [eight.pick_id, eight.pick_id, 'nope', unpriced.pick_id])).toEqual({ count: 1, credits: 91 });
    expect(selectionTotal(rows, [adjusted.pick_id])).toEqual({ count: 1, credits: 135 });
    expect(selectionTotal(rows, [])).toEqual({ count: 0, credits: 0 });
  });
});

describe('makeMany (Review Focus 5)', () => {
  const fake = (refuse: Record<string, string> = {}, dispatched: Record<string, boolean> = {}) => {
    const calls: { id: string; kind: string; adjust: DropAdjust | null }[] = [];
    let active = 0;
    let most = 0;
    return {
      calls,
      most: () => most,
      backend: {
        async requestJob(id: string, kind: 'process' | 'make', adjust: DropAdjust | null = null) {
          active += 1;
          most = Math.max(most, active);
          calls.push({ id, kind, adjust });
          await new Promise((r) => setTimeout(r, 2));
          active -= 1;
          if (refuse[id]) throw new Error(refuse[id]);
          return { dispatched: dispatched[id] ?? true };
        },
      },
    };
  };

  it('asks Make it for each pick, one at a time, and reports each pick’s own result: a refusal does not hide the others', async () => {
    const f = fake({ b: 'Make it needs a checked and priced drop (ready); this one is making' }, { c: false });
    const results = await makeMany(f.backend, ['a', 'b', 'c']);
    expect(f.calls.map((c) => [c.id, c.kind])).toEqual([['a', 'make'], ['b', 'make'], ['c', 'make']]);
    expect(f.most()).toBe(1); // one by one
    expect(results).toEqual([
      { pickId: 'a', ok: true, dispatched: true, message: 'Sent: making starts now' },
      { pickId: 'b', ok: false, dispatched: false, message: 'Make it needs a checked and priced drop (ready); this one is making' },
      { pickId: 'c', ok: true, dispatched: false, message: 'Sent: the next run starts it' },
    ]);
    expect(makeSummary(results)).toBe('2 clips sent to be made, 1 refused: Make it needs a checked and priced drop (ready); this one is making');
  });

  it('sends each clip once, with the Adjust it shows its price for', async () => {
    const f = fake();
    const stored: DropAdjust = { length_s: 12 };
    const results = await makeMany(f.backend, ['a', 'b', 'a'], (id) => (id === 'b' ? stored : null));
    expect(f.calls).toEqual([{ id: 'a', kind: 'make', adjust: null }, { id: 'b', kind: 'make', adjust: stored }]);
    expect(results.map((r) => r.pickId)).toEqual(['a', 'b']);
  });

  it('says how it went in one line', async () => {
    expect(makeSummary([{ pickId: 'a', ok: true, dispatched: true, message: '' }])).toBe('1 clip sent to be made');
    expect(makeSummary([])).toBe('Nothing was sent');
    const f = fake({ a: 'no', b: 'no either' });
    expect(makeSummary(await makeMany(f.backend, ['a', 'b']))).toBe('Nothing was sent, 2 refused: no');
  });
});

// ---- the demo has something for every new block ---------------------------------------------------------------------------------

describe('the demo', () => {
  it('has scored Ready clips with one unscored, a family of a root and a version, and a clip another character may take', async () => {
    const { DemoBackend } = await import('../demo/backend');
    const snap = await new DemoBackend(() => NOW).load();
    const ready = snap.tracker.filter((r) => r.drop_card?.state === 'ready');
    expect(ready.filter((r) => scoreOf(r) != null).length).toBeGreaterThanOrEqual(4);
    expect(ready.some((r) => scoreOf(r) == null)).toBe(true); // a clip checked before the score
    for (const r of ready.filter((x) => x.drop_card?.score)) {
      const s = r.drop_card!.score!;
      expect(s.total).toBe(Math.round(10 * (0.6 * s.potential + 0.4 * s.swap)));
    }
    const live = snap.characters.filter((c) => c.status === 'live');
    expect(live.some((c) => topPicks(snap.tracker.filter((r) => r.character_slug === c.slug)).length === 3)).toBe(true);
    const versions = snap.tracker.filter((r) => r.drop_card?.copy_of);
    expect(versions.length).toBeGreaterThanOrEqual(1);
    const family = familyOf(versions[0], snap.tracker);
    expect(family.length).toBe(2);
    expect(family[0].drop_card?.source_id).toBe(versions[0].drop_card?.source_id); // one clip, shared
    expect(snap.tracker.some((r) => reuseTargets(r, snap.characters, snap.tracker).length > 0)).toBe(true);
    expect(snap.characters.every((c) => Array.isArray(c.setup.stars))).toBe(true);
  });

  it('files a version like copy_drop: the root’s clip, checked again in his voice, a version of a version at the root, the same refusals', async () => {
    const { DemoBackend } = await import('../demo/backend');
    let now = NOW;
    const demo = new DemoBackend(() => now);
    let snap = await demo.load();
    const root = snap.tracker.find((r) => r.drop_card?.state === 'ready' && !r.drop_card.copy_of && r.drop_card.star?.kind === 'person'
      && familyOf(r, snap.tracker).length === 1 && r.character_slug === 'lenny')!;
    expect(root).toBeTruthy();
    const { pickId, dispatched } = await demo.copyDrop(root.pick_id, 'reginald');
    expect(dispatched).toBe(true);
    snap = await demo.load();
    const v = snap.tracker.find((r) => r.pick_id === pickId)!;
    expect(v).toMatchObject({ character_slug: 'reginald', url: `owner-drop:${pickId}`, platform: 'drop', status: 'approved' });
    expect(v.drop_card).toMatchObject({ state: 'checking', character_by: 'owner', copy_of: root.pick_id, source_id: root.drop_card!.source_id });
    expect(v.drop_card?.score).toBeUndefined();
    now += 2_500;
    snap = await demo.load();
    const checked = snap.tracker.find((r) => r.pick_id === pickId)!.drop_card!;
    expect(checked.state).toBe('ready');
    expect(checked.score?.total).toEqual(expect.any(Number)); // its own check, its own score
    // the same character twice, a paused one, an unknown one, the wrong star; asked from the version: points at the root
    await expect(demo.copyDrop(pickId, 'reginald')).rejects.toThrow('Reginald already has a version of this clip');
    await expect(demo.copyDrop(root.pick_id, 'lenny')).rejects.toThrow('Lenny Gold already has a version of this clip');
    await expect(demo.copyDrop(root.pick_id, 'biscuit')).rejects.toThrow('Biscuit is paused');
    await expect(demo.copyDrop(root.pick_id, 'nobody')).rejects.toThrow("unknown character 'nobody'");
    await expect(demo.copyDrop(root.pick_id, 'franz')).rejects.toThrow("the wrong star: Franz replaces a dog, this clip's star is a person");
    const checking = snap.tracker.find((r) => r.drop_card?.state === 'checking' && !r.drop_card.copy_of)!;
    await expect(demo.copyDrop(checking.pick_id, 'reginald')).rejects.toThrow('the clip is not checked yet');
    await expect(demo.copyDrop('nope', 'reginald')).rejects.toThrow(/unknown pick/);
  });
});
