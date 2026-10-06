// "Drop a video" (plan 2026-10-06): the card rules, the Adjust (the same keys and limits as studio.drop.validate_adjust and
// request_job in migration 0012), the price, the tracker mapping and the demo, which has a drop in every state and runs the
// whole flow: drop, upload, check, Make it.
import { readFileSync } from 'node:fs';
import { describe, expect, it } from 'vitest';
import {
  ADJUST_KEYS, DROP_STATE_LABEL, dropsFirst, STALE_UPLOAD_MINUTES, adjustChanges, dropActions, dropCredits, dropLine, dropLink, dropTitle, effectiveDrop,
  isDropCard, isLandscape, sectionLabel, validateAdjust,
} from './drop';
import { estimateCredits } from './rules';
import { trackerStep } from './tracker';
import type { DropCard, DropState, TrackerRow } from './types';

const NOW = Date.parse('2026-10-06T12:00:00Z');
const MIN = 60_000;
const ago = (m: number) => new Date(NOW - m * MIN).toISOString();

const READY: DropCard = {
  state: 'ready', kind: 'file', at: ago(5), source_id: 's1', duration_s: 20, width: 1080, height: 1920,
  window: { start_s: 1.5, length_s: 9 }, crop_x: null,
  star: { kind: 'person', body: 'biped', description: 'the man in the grey suit', x_center: 0.5 },
  part: 'featured', gadgets: ['black umbrella'], hooks: ['The household is unaware.', 'b', 'c'], hook: 'The household is unaware.',
  credits: 102, seconds: 9, music: 'original', preview_path: 'owner/x/preview.jpg',
};
const LANDSCAPE: DropCard = { ...READY, width: 1920, height: 1080, crop_x: 0.4 };

const row = (drop: DropCard | null, over: Partial<TrackerRow> = {}): TrackerRow => ({
  pick_id: 'p1', character_slug: 'reginald', character_name: 'Reginald', url: 'owner-drop:p1', platform: 'drop', creator_handle: null,
  views: null, outlier_x: null, tier: null, theme: null, concept: null, hook: null, thumbnail_url: null, preview_url: null, gallery: false,
  posted_at: null, velocity: null, proposed_mode: null, owner_mode: null, owner_presence: null, owner_music: null, owner_clip_path: null,
  status: 'approved', decision: { decision: 'approve', by: 'owner', reason: "owner's own video" }, approved_at: ago(10), note: null,
  source_id: null, analysis: null, fetch_failed: null, clip_id: null, clip_state: null, clip_mode: null, clip_state_since: null,
  clip_failure: null, credits_spent: 0, post_id: null, post_status: null, post_scheduled_for: null, post_posted_at: null, post_url: null,
  post_error: null, latest_views: null, caption: null, hashtags: null, first_comment: null, drop_card: drop, make_requested_at: null,
  ...over,
});

describe('the card of a dropped video', () => {
  it('stays on its own card until Make it, then the stepper takes over', () => {
    for (const state of ['uploading', 'checking', 'waiting', 'ready', 'blocked', 'failed'] as DropState[]) {
      expect([state, isDropCard(row({ ...READY, state }))]).toEqual([state, true]);
    }
    expect(isDropCard(row({ ...READY, state: 'making' }))).toBe(false);
    expect(isDropCard(row({ ...READY, state: 'made' }, { clip_id: 'c', clip_state: 'awaiting_approval' }))).toBe(false);
    expect(isDropCard(row(null))).toBe(false); // a scan pick: the stepper as before
    expect(Object.keys(DROP_STATE_LABEL).sort()).toEqual(['blocked', 'checking', 'failed', 'made', 'making', 'ready', 'uploading', 'waiting']);
  });

  it('has the right buttons: Make it and Adjust when ready, Try again after a failure, Remove when it cannot go on', () => {
    expect(dropActions(READY, NOW)).toEqual(['make', 'adjust']);
    expect(dropActions({ ...READY, state: 'blocked' }, NOW)).toEqual(['remove']);
    expect(dropActions({ ...READY, state: 'failed' }, NOW)).toEqual(['retry-make', 'remove']); // priced: Make it again
    expect(dropActions({ state: 'failed' }, NOW)).toEqual(['retry-check', 'remove']); // the check itself failed
    expect(dropActions({ state: 'waiting' }, NOW)).toEqual(['retry-check', 'remove']);
    expect(dropActions({ state: 'checking' }, NOW)).toEqual([]);
    expect(dropActions({ state: 'uploading', at: ago(2) }, NOW)).toEqual([]);
    expect(dropActions({ state: 'uploading', at: ago(STALE_UPLOAD_MINUTES + 1) }, NOW)).toEqual(['remove']);
  });

  it('says in one line where it is; the database’s reason wins', () => {
    expect(dropLine(READY, NOW)).toBe('Replaces the man in the grey suit · Featured · 1.5–10.5 s (9 s)');
    expect(dropLine({ state: 'blocked', reason: 'the star is a child: our character only replaces an adult' }, NOW)).toBe('the star is a child: our character only replaces an adult');
    expect(dropLine({ state: 'uploading', at: ago(STALE_UPLOAD_MINUTES + 5) }, NOW)).toMatch(/did not finish/);
    expect(dropTitle({ concept: 'A man dances\nmore', drop_card: READY })).toBe('A man dances');
    expect(dropTitle({ concept: null, drop_card: { state: 'checking', kind: 'link' } })).toBe('Your link');
    expect(dropTitle({ concept: null, drop_card: { state: 'uploading', kind: 'file' } })).toBe('Your video');
    expect(sectionLabel(2, 12.5)).toBe('2–14.5 s (12.5 s)');
  });

  it('prices the section like studio.planning.estimate_credits, the Adjust included', () => {
    expect(dropCredits(READY)).toBe(estimateCredits('dropin', 9, 'original'));
    expect(dropCredits(READY, { length_s: 14 })).toBe(Math.ceil(14 * 11) + 3);
  });
});

describe('the Adjust: the same rules as the CLI and request_job', () => {
  it('names the same seven keys as studio.drop.ADJUST_KEYS and migration 0012', () => {
    const py = readFileSync(new URL('../../../studio/drop.py', import.meta.url), 'utf8');
    const sql = readFileSync(new URL('../../../supabase/migrations/0012_drop_a_video.sql', import.meta.url), 'utf8');
    const keys = ADJUST_KEYS.map((k) => `"${k}"`).join(', ');
    expect(py).toContain(`ADJUST_KEYS = (${keys})`);
    expect(sql).toContain(`k not in (${ADJUST_KEYS.map((k) => `'${k}'`).join(', ')})`);
  });

  it('accepts a fitting Adjust and refuses each broken rule with its reason', () => {
    expect(validateAdjust({ part: 'star', start_s: 4, length_s: 14, gadgets: ['gold chain'], hook: 'Tea is at four.' }, READY)).toEqual({ ok: true });
    const bad: [Parameters<typeof validateAdjust>[0], RegExp][] = [
      [{ length_s: 5 }, /6-16 s/], [{ length_s: 17 }, /6-16 s/], [{ start_s: 15, length_s: 9 }, /runs past the end/], [{ start_s: -1 }, /0 s or later/],
      [{ part: 'lead' as never }, /cameo, featured or star/], [{ gadgets: ['a', 'b', 'c', 'd'] }, /at most 3/], [{ hook: 'x'.repeat(81) }, /1-80/],
      [{ star: ' ' }, /1-80/], [{ crop_x: 1.5 }, /from 0 to 1/], [{ crop_x: 0.5 }, /already vertical/],
      [{ colour: 'red' } as never, /unknown setting/],
    ];
    for (const [adjust, reason] of bad) {
      const r = validateAdjust(adjust, READY);
      expect([adjust, r.ok]).toEqual([adjust, false]);
      if (!r.ok) expect(r.reason).toMatch(reason);
    }
    expect(validateAdjust({ crop_x: 0.2 }, LANDSCAPE)).toEqual({ ok: true });
    expect(isLandscape(LANDSCAPE) && !isLandscape(READY)).toBe(true);
  });

  it('sends only what the owner changed', () => {
    const base = effectiveDrop(READY);
    const same = { ...base, gadgets: [...base.gadgets], crop_x: null };
    expect(adjustChanges(READY, same)).toEqual({});
    expect(adjustChanges(READY, { ...same, part: 'star', length_s: 12 })).toEqual({ part: 'star', start_s: 1.5, length_s: 12 });
    expect(adjustChanges(READY, { ...same, crop_x: 0.3 })).toEqual({}); // a vertical clip: no crop to send
    expect(adjustChanges(LANDSCAPE, { ...effectiveDrop(LANDSCAPE), crop_x: 0.25 })).toEqual({ crop_x: 0.25 });
    expect(adjustChanges(READY, { ...same, gadgets: [] })).toEqual({ gadgets: [] });
  });
});

describe('the drop box', () => {
  it('takes a full link and refuses a short one', () => {
    expect(dropLink('https://www.tiktok.com/@dancer.one/video/7688386199270001953?is_from_webapp=1')).toEqual({
      ok: true, url: 'https://www.tiktok.com/@dancer.one/video/7688386199270001953',
    });
    const short = dropLink('https://vm.tiktok.com/ZM123/');
    expect(short.ok).toBe(false);
    if (!short.ok) expect(short.reason).toMatch(/short links/);
  });
});

describe('the tracker maps a drop onto the first steps until its clip exists', () => {
  it('uploading, checking, waiting and blocked are step 1; ready is 2; making is 3', () => {
    expect(trackerStep(row({ state: 'checking', at: ago(1) }), NOW)).toMatchObject({ step: 1, state: 'ok' });
    expect(trackerStep(row({ state: 'waiting', reason: 'the Mac tries again' }), NOW)).toMatchObject({ step: 1, state: 'waiting' });
    expect(trackerStep(row({ state: 'blocked', reason: 'the star is a child' }), NOW)).toMatchObject({ step: 1, state: 'failed', reason: 'the star is a child' });
    expect(trackerStep(row(READY), NOW)).toMatchObject({ step: 2, state: 'ok', note: `Ready: about ${dropCredits(READY)} credits` });
    expect(trackerStep(row({ ...READY, state: 'making' }), NOW)).toMatchObject({ step: 3, state: 'ok' });
    expect(trackerStep(row({ ...READY, state: 'making', reason: 'waiting for the Higgsfield key' }), NOW)).toMatchObject({ step: 3, state: 'waiting' });
    // never the "no clip yet" flag of a scan pick, however long it waits
    expect(trackerStep(row({ ...READY }, { approved_at: ago(60 * 48) }), NOW).reason).toBeNull();
    // with its clip, the job's waiting line is the note of a moving step
    const gen = row({ ...READY, state: 'making', reason: 'Higgsfield is still working' }, { clip_id: 'c', clip_state: 'generating', clip_state_since: ago(10), status: 'queued' });
    expect(trackerStep(gen, NOW)).toMatchObject({ step: 3, state: 'ok', note: 'Higgsfield is still working' });
  });
});

describe('the demo', () => {
  it('has a drop in every state', async () => {
    const { DemoBackend } = await import('../demo/backend');
    const snap = await new DemoBackend(() => NOW).load();
    const states = new Set(snap.tracker.map((r) => r.drop_card?.state).filter(Boolean));
    expect([...states].sort()).toEqual(['blocked', 'checking', 'failed', 'made', 'making', 'ready', 'uploading', 'waiting']);
    const ready = snap.tracker.filter((r) => r.drop_card?.state === 'ready');
    expect(ready.some((r) => isLandscape(r.drop_card!)) && ready.some((r) => !isLandscape(r.drop_card!))).toBe(true);
    for (const r of ready) expect(r.drop_card!.credits).toBe(dropCredits(r.drop_card!));
    expect(snap.tracker.some((r) => r.drop_card?.state === 'making' && r.clip_state === 'generating')).toBe(true);
    expect(snap.tracker.some((r) => r.drop_card?.state === 'making' && r.clip_state == null && r.drop_card.reason)).toBe(true);
    expect(snap.tracker.some((r) => r.drop_card?.state === 'made' && r.clip_state === 'awaiting_approval')).toBe(true);
    for (const r of snap.tracker.filter((x) => x.drop_card)) {
      expect(Object.keys(r.drop_card!)).not.toContain('deconstruct'); // the card never carries the job's internals
      expect(trackerStep(r, NOW).step).toBeGreaterThanOrEqual(1);
    }
  });

  it('runs the whole flow: several files dropped, uploaded, checked, then Make it with an Adjust', async () => {
    const { DemoBackend } = await import('../demo/backend');
    let now = NOW;
    const demo = new DemoBackend(() => now);
    const ids: string[] = [];
    for (const name of ['a.mp4', 'b.mov']) {
      const { pickId, duplicate } = await demo.addDrop('reginald', null);
      expect(duplicate).toBe(false);
      await expect(demo.requestJob(pickId, 'process')).rejects.toThrow(/upload has not finished/);
      await demo.attachClip(pickId, { name, size: 1000, type: name.endsWith('.mov') ? 'video/quicktime' : 'video/mp4' });
      await demo.requestJob(pickId, 'process');
      ids.push(pickId);
    }
    let snap = await demo.load();
    expect(ids.map((id) => snap.tracker.find((r) => r.pick_id === id)?.drop_card?.state)).toEqual(['checking', 'checking']);
    now += 2_500;
    snap = await demo.load();
    const card = snap.tracker.find((r) => r.pick_id === ids[0])!.drop_card!;
    expect(card.state).toBe('ready');
    await expect(demo.requestJob(ids[0], 'make', { length_s: 40 })).rejects.toThrow(/6-16 s|runs past/);
    await demo.requestJob(ids[0], 'make', { part: 'star', length_s: 8 });
    snap = await demo.load();
    const making = snap.tracker.find((r) => r.pick_id === ids[0])!;
    expect(making.drop_card?.state).toBe('making');
    expect(making.drop_card?.adjust).toEqual({ part: 'star', length_s: 8 });
    expect(making.make_requested_at).toBe(new Date(now).toISOString());
    now += 2_500;
    snap = await demo.load();
    expect(trackerStep(snap.tracker.find((r) => r.pick_id === ids[0])!, now).step).toBe(3); // generating, on the stepper
    await demo.decidePick(ids[1], 'skip', 'removed by the owner', null); // Remove
    expect((await demo.load()).tracker.some((r) => r.pick_id === ids[1])).toBe(false);
  });

  it('files a link as checking and refuses Make it on a drop that is not ready', async () => {
    const { DemoBackend } = await import('../demo/backend');
    const demo = new DemoBackend(() => NOW);
    const { pickId } = await demo.addDrop('biscuit', 'https://www.tiktok.com/@dancer.one/video/7688386199270001953');
    const r = (await demo.load()).tracker.find((t) => t.pick_id === pickId)!;
    expect(r.drop_card?.state).toBe('checking') ;
    expect(r.creator_handle).toBe('@dancer.one');
    await expect(demo.requestJob(pickId, 'make')).rejects.toThrow(/needs a checked and priced drop/);
    expect((await demo.previewUrl('owner/x/preview.jpg'))?.startsWith('data:image/svg+xml')).toBe(true);
  });
});

describe('own footage or a downloaded clip (owner 2026-10-06)', () => {
  it('starts as a downloaded clip, the toggle sets it, and the demo shows both', async () => {
    const { DemoBackend } = await import('../demo/backend');
    const demo = new DemoBackend(() => NOW);
    const snap = await demo.load();
    const drops = snap.tracker.filter((r) => r.drop_card);
    expect(drops.some((r) => r.drop_card!.own_footage === true) && drops.some((r) => r.drop_card!.own_footage === false)).toBe(true);
    const { pickId } = await demo.addDrop('biscuit', null);
    const card = async () => (await demo.load()).tracker.find((r) => r.pick_id === pickId)!.drop_card!;
    expect((await card()).own_footage).toBe(false);
    await demo.setDropFootage(pickId, true);
    expect((await card()).own_footage).toBe(true);
    await expect(demo.setDropFootage(snap.tracker.find((r) => !r.drop_card)!.pick_id, true)).rejects.toThrow(/not a dropped video/);
  });

  it('never changes what Make it sends or costs', () => {
    expect(dropCredits({ ...READY, own_footage: true })).toBe(dropCredits(READY));
    expect(effectiveDrop({ ...READY, own_footage: true })).toEqual(effectiveDrop(READY));
  });
});

describe('the order in a group', () => {
  it('puts the drops on their own card first, newest on top, then the rest as the tracker orders them', () => {
    const a = row({ ...READY, at: ago(30) }, { pick_id: 'a' });
    const b = row({ state: 'checking', at: ago(2) }, { pick_id: 'b' });
    const scan = row(null, { pick_id: 's' });
    const made = row({ ...READY, state: 'made' }, { pick_id: 'm', clip_id: 'c', clip_state: 'awaiting_approval' });
    expect(dropsFirst([scan, a, made, b]).map((r) => r.pick_id)).toEqual(['b', 'a', 's', 'm']);
  });
});
