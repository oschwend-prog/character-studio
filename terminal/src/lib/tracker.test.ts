import { describe, expect, it } from 'vitest';
import {
  NO_CLIP_HOURS, POSTED_KEEP_DAYS, STUCK_HOURS, TRACKER_STEPS, clipReady, compareTracker, durationLabel, groupTracker, inTracker,
  musicLabel, slotLabel, timeAtStep, trackerMode, trackerStep, trackerTitle,
} from './tracker';
import type { TrackerRow } from './types';

const NOW = Date.parse('2026-10-06T12:00:00Z'); // Tue 6 Oct, 13:00 London
const HOUR = 3_600_000;
const ago = (hours: number) => new Date(NOW - hours * HOUR).toISOString();

let n = 0;
const row = (over: Partial<TrackerRow> = {}): TrackerRow => {
  n += 1;
  return {
    pick_id: `pick-${String(n).padStart(3, '0')}`, character_slug: 'biscuit', character_name: 'Biscuit', url: `https://www.tiktok.com/@a/video/${n}`,
    platform: 'tiktok', creator_handle: '@a', views: 2_000_000, outlier_x: 40, tier: null, theme: null, concept: 'Hop and lasso\nmore',
    hook: 'oppan sausage style', thumbnail_url: null, preview_url: null, gallery: false, posted_at: ago(72), velocity: null,
    proposed_mode: 'dropin', owner_mode: null, owner_presence: null, owner_music: null, owner_clip_path: null, status: 'approved',
    decision: { decision: 'approve', by: 'rule', reason: 'rule: total 84 >= 80' }, approved_at: ago(2), note: null, source_id: null,
    analysis: null, fetch_failed: null, clip_id: null, clip_state: null, clip_mode: null, clip_state_since: null, clip_failure: null,
    credits_spent: 0, post_id: null, post_status: null, post_scheduled_for: null, post_posted_at: null, post_url: null, post_error: null,
    latest_views: null,
    ...over,
  };
};
const clip = (state: TrackerRow['clip_state'], hours = 1, over: Partial<TrackerRow> = {}) =>
  row({ status: 'queued', clip_id: `clip-${n}`, clip_state: state, clip_mode: 'dropin', clip_state_since: ago(hours), ...over });
const ANALYSIS = { people_count: 1, camera: 'static' as const, watermark: false, overlay: false, minors: false, best_window: { start_s: 1.5, end_s: 9.5 } };

describe('trackerStep: the 8 steps', () => {
  it('1 Approved: nothing else yet, flagged "no clip yet" after a day', () => {
    expect(trackerStep(row(), NOW)).toMatchObject({ step: 1, state: 'ok', reason: null });
    expect(trackerStep(row({ approved_at: ago(NO_CLIP_HOURS + 1) }), NOW)).toMatchObject({ step: 1, state: 'waiting', reason: 'no clip yet' });
  });

  it('2 Clip ready: a gallery preset, a checked, stored or attached clip, or a Recreate', () => {
    expect(trackerStep(row({ gallery: true, approved_at: ago(30) }), NOW)).toMatchObject({ step: 2, state: 'ok', note: 'Genjutsu gallery clip: ready to drop in' });
    expect(trackerStep(row({ analysis: ANALYSIS }), NOW).note).toBe('Clip checked: 1 person · static camera · best 1.5-9.5 s');
    expect(trackerStep(row({ source_id: 'src-1' }), NOW)).toMatchObject({ step: 2, note: 'Clip in the library' });
    expect(trackerStep(row({ owner_clip_path: 'owner/p/1.mp4' }), NOW)).toMatchObject({ step: 2, note: 'Your clip is attached' });
    expect(trackerStep(row({ owner_mode: 'recreate' }), NOW)).toMatchObject({ step: 2, note: 'Recreate: we make our own driver' });
    expect(trackerStep(row({ proposed_mode: 'recreate' }), NOW).step).toBe(2);
    expect(trackerStep(row({ owner_mode: 'dropin', fetch_failed: { reason: 'login wall' } }), NOW).note).toMatch(/could not be fetched/);
    expect(clipReady(row())).toBeNull();
  });

  it('3 Generating: planned or generating, gen_failed is failed', () => {
    expect(trackerStep(clip('planned'), NOW)).toMatchObject({ step: 3, state: 'ok' });
    expect(trackerStep(clip('generating', 2), NOW)).toMatchObject({ step: 3, state: 'ok', reason: null });
    expect(trackerStep(clip('gen_failed'), NOW)).toMatchObject({ step: 3, state: 'failed', reason: 'generation failed: the next run tries again' });
    expect(trackerStep(clip('gen_failed', 1, { clip_failure: 'Higgsfield refused the job' }), NOW).reason).toBe('Higgsfield refused the job');
    expect(trackerStep(row({ status: 'queued' }), NOW)).toMatchObject({ step: 3, state: 'ok' }); // queued, its clip row not seen yet
  });

  it('4 Quality check: generated or passed; failed says re-roll once', () => {
    expect(trackerStep(clip('generated'), NOW)).toMatchObject({ step: 4, state: 'ok' });
    expect(trackerStep(clip('qa_passed'), NOW)).toMatchObject({ step: 4, state: 'ok' });
    expect(trackerStep(clip('qa_failed', 1, { clip_failure: 'the quiff moves at 4 s' }), NOW)).toMatchObject({
      step: 4, state: 'failed', reason: 'the quiff moves at 4 s: re-roll once',
    });
  });

  it('5 Video built, 6 Your OK with the way to the Queue, rejected is failed', () => {
    expect(trackerStep(clip('mastered'), NOW)).toMatchObject({ step: 5, state: 'ok' });
    expect(trackerStep(clip('awaiting_approval', 1, { status: 'made' }), NOW)).toMatchObject({ step: 6, state: 'ok', action: 'queue' });
    expect(trackerStep(clip('rejected', 1, { status: 'made', clip_failure: 'eyes swapped' }), NOW)).toMatchObject({
      step: 6, state: 'failed', reason: 'rejected: eyes swapped',
    });
  });

  it('7 Scheduled shows the slot in London time; 8 Posted, and a failed or unchecked post is failed with its error', () => {
    const slot = '2026-10-06T18:00:00Z'; // 19:00 London (BST)
    expect(trackerStep(clip('scheduled', 1, { status: 'made', post_status: 'scheduled', post_scheduled_for: slot }), NOW)).toMatchObject({
      step: 7, state: 'ok', note: 'Tue 19:00',
    });
    expect(trackerStep(clip('approved', 1, { status: 'made' }), NOW)).toMatchObject({ step: 7, state: 'ok' });
    const posted = trackerStep(clip('posted', 30, { status: 'made', post_status: 'posted', post_posted_at: ago(3), post_scheduled_for: ago(3) }), NOW);
    expect(posted).toMatchObject({ step: 8, state: 'ok', done: true });
    expect(trackerStep(clip('scheduled', 1, { status: 'made', post_status: 'posting' }), NOW)).toMatchObject({ step: 8, state: 'ok', note: 'posting now' });
    expect(trackerStep(clip('scheduled', 1, { status: 'made', post_status: 'failed', post_error: 'Postiz 500' }), NOW)).toMatchObject({
      step: 8, state: 'failed', reason: 'Postiz 500',
    });
    expect(trackerStep(clip('scheduled', 1, { status: 'made', post_status: 'needs_check' }), NOW)).toMatchObject({
      step: 8, state: 'failed', reason: 'needs a check: is it live?',
    });
  });

  it('a dropped clip is grey with its reason, and a returned pick says it is back in line', () => {
    const budget = trackerStep(clip('dropped', 3, { status: 'queued', note: 'clip dropped: over the budget' }), NOW);
    expect(budget).toMatchObject({ step: 3, state: 'dropped', reason: 'clip dropped: over the budget' });
    const qa = trackerStep(clip('dropped', 3, { status: 'approved', clip_failure: 'smile at 6 s', credits_spent: 160 }), NOW);
    expect(qa).toMatchObject({ step: 4, state: 'dropped', reason: 'smile at 6 s · back in line for the next run' });
  });

  it('flags "stuck?" after 6 hours at Generating or Quality check, and nowhere else', () => {
    for (const state of ['planned', 'generating', 'generated', 'qa_passed'] as const) {
      expect(trackerStep(clip(state, STUCK_HOURS - 0.5), NOW).state).toBe('ok');
      expect(trackerStep(clip(state, STUCK_HOURS + 0.5), NOW)).toMatchObject({ state: 'waiting', reason: 'stuck?' });
    }
    expect(trackerStep(clip('mastered', 30), NOW).state).toBe('ok');
    expect(trackerStep(clip('awaiting_approval', 30, { status: 'made' }), NOW).state).toBe('ok');
  });
});

describe('who is listed and in which order', () => {
  it('keeps a posted pick for 7 days after its post went out, and never a new or skipped one', () => {
    const posted = (days: number) => row({ status: 'made', post_status: 'posted', post_posted_at: ago(days * 24) });
    expect(inTracker(posted(POSTED_KEEP_DAYS - 1), NOW)).toBe(true);
    expect(inTracker(posted(POSTED_KEEP_DAYS + 0.1), NOW)).toBe(false);
    expect(inTracker(row({ status: 'made', post_status: null }), NOW)).toBe(true);
    expect(inTracker(row({ status: 'made', post_status: 'failed', post_scheduled_for: ago(24 * 20) }), NOW)).toBe(true);
    for (const status of ['approved', 'analysed', 'queued']) expect(inTracker(row({ status }), NOW)).toBe(true);
    for (const status of ['new', 'skipped']) expect(inTracker(row({ status }), NOW)).toBe(false);
  });

  it('sorts by scheduled time first, then the rest by approval time, oldest first', () => {
    const later = row({ post_scheduled_for: '2026-10-08T18:00:00Z' });
    const sooner = row({ post_scheduled_for: '2026-10-06T18:00:00Z' });
    const oldApproval = row({ approved_at: ago(40) });
    const newApproval = row({ approved_at: ago(1) });
    const sorted = [newApproval, later, oldApproval, sooner].sort(compareTracker).map((r) => r.pick_id);
    expect(sorted).toEqual([sooner.pick_id, later.pick_id, oldApproval.pick_id, newApproval.pick_id]);
  });

  it('groups by character in roster order, drops what is not listed, and puts the unassigned last', () => {
    const roster = [{ slug: 'biscuit', name: 'Biscuit' }, { slug: 'reginald', name: 'Reginald' }];
    const r1 = row({ character_slug: 'reginald', character_name: 'Reginald' });
    const b1 = row();
    const gone = row({ status: 'made', post_status: 'posted', post_posted_at: ago(24 * 9) });
    const nobody = row({ character_slug: null, character_name: null });
    const groups = groupTracker([r1, gone, b1, nobody], roster, NOW);
    expect(groups.map((g) => [g.slug, g.rows.map((r) => r.pick_id)])).toEqual([
      ['biscuit', [b1.pick_id]], ['reginald', [r1.pick_id]], [null, [nobody.pick_id]],
    ]);
    expect(groupTracker([], roster, NOW)).toEqual([]);
  });
});

describe('the words on a card', () => {
  it('says how long it has been at the step, or when it was posted', () => {
    expect(timeAtStep(trackerStep(clip('generating', 2), NOW), NOW)).toBe('2 h at Generating');
    expect(timeAtStep(trackerStep(clip('generating', 0.2), NOW), NOW)).toBe('12 min at Generating');
    expect(timeAtStep(trackerStep(row({ approved_at: ago(75) }), NOW), NOW)).toBe('3 d at Approved');
    const posted = trackerStep(clip('posted', 30, { status: 'made', post_status: 'posted', post_posted_at: ago(3) }), NOW);
    expect(timeAtStep(posted, NOW)).toBe('posted 3 h ago');
    const failed = trackerStep(clip('scheduled', 30, { status: 'made', post_status: 'failed', post_scheduled_for: ago(2) }), NOW);
    expect(timeAtStep(failed, NOW)).toBe('slot 2 h ago');
    const booked = trackerStep(clip('scheduled', 3, { status: 'made', post_status: 'scheduled', post_scheduled_for: '2026-10-06T18:00:00Z' }), NOW);
    expect(timeAtStep(booked, NOW)).toBe('3 h at Scheduled');
    expect(timeAtStep(trackerStep(clip('mastered', 1, { clip_state_since: null }), NOW), NOW)).toBeNull();
    expect([durationLabel(0), durationLabel(59 * 60_000), durationLabel(47 * HOUR), durationLabel(49 * HOUR)]).toEqual(['1 min', '59 min', '47 h', '2 d']);
    expect(TRACKER_STEPS).toHaveLength(8);
  });

  it('names the slot, the mode, the music and the title', () => {
    expect(slotLabel('2026-10-06T18:00:00Z')).toBe('Tue 19:00');
    expect(slotLabel('2026-11-03T19:30:00Z')).toBe('Tue 19:30'); // GMT in November
    expect(trackerMode(row({ clip_mode: 'recreate', owner_mode: 'dropin' }))).toBe('recreate');
    expect(trackerMode(row({ owner_mode: null, proposed_mode: 'dropin', fetch_failed: { reason: 'x' } }))).toBe('recreate');
    expect(musicLabel(row({ owner_music: 'in_app' }))).toBe('Add in Instagram app');
    expect(musicLabel(row({ proposed_mode: 'dropin' }))).toBe('Keep original audio');
    expect(musicLabel(row({ proposed_mode: 'recreate' }))).toBe('AI beat (+30)');
    expect(trackerTitle(row())).toBe('Hop and lasso');
    expect(trackerTitle(row({ concept: null }))).toBe('“oppan sausage style”');
  });
});

// ---- the demo shows every step and every flag ----------------------------------------------------------------------------------------

describe('the demo data', () => {
  it('has a pick at every one of the 8 steps and every flag of "In the works", and drops a week-old post', async () => {
    const { DemoBackend } = await import('../demo/backend');
    const snap = await new DemoBackend(() => NOW).load();
    const steps = snap.tracker.map((r) => ({ r, s: trackerStep(r, NOW) }));
    expect(new Set(steps.map(({ s }) => s.step))).toEqual(new Set([1, 2, 3, 4, 5, 6, 7, 8]));
    const has = (pred: (x: { r: TrackerRow; s: ReturnType<typeof trackerStep> }) => boolean) => expect(steps.some(pred)).toBe(true);
    has(({ s }) => s.step === 1 && s.reason === 'no clip yet');
    has(({ s }) => s.step === 1 && s.state === 'ok');
    for (const note of ['Genjutsu gallery clip', 'Clip checked', 'Recreate: we make our own driver']) has(({ s }) => s.step === 2 && (s.note ?? '').startsWith(note));
    has(({ s }) => s.step === 3 && s.reason === 'stuck?');
    has(({ s }) => s.step === 3 && s.state === 'failed');
    has(({ s }) => s.step === 4 && s.reason === 'stuck?');
    has(({ s }) => s.step === 4 && s.state === 'failed' && /re-roll once/.test(s.reason ?? ''));
    has(({ s }) => s.step === 6 && s.action === 'queue');
    has(({ s }) => s.step === 6 && s.state === 'failed');
    has(({ s }) => s.step === 7 && /^\w{3} \d\d:\d\d$/.test(s.note ?? ''));
    has(({ s, r }) => s.step === 8 && s.done && r.post_url != null && r.latest_views != null);
    has(({ r, s }) => s.step === 8 && s.state === 'failed' && r.post_status === 'failed');
    has(({ r, s }) => s.step === 8 && s.state === 'failed' && r.post_status === 'needs_check');
    has(({ s }) => s.state === 'dropped' && /back in line/.test(s.reason ?? ''));
    has(({ r }) => r.credits_spent > 0);
    expect(snap.tracker.some((r) => r.hook === "my eyes don't match. my moves do.")).toBe(false); // posted 13 days ago: off the list
    const groups = groupTracker(snap.tracker, snap.characters, NOW);
    expect(groups.map((g) => g.slug)).toEqual(['biscuit', 'reginald']);
  });

  it('carries every field of the long list on some new pick, and none of it on others', async () => {
    const { DemoBackend } = await import('../demo/backend');
    const picks = (await new DemoBackend(() => NOW).load()).picks;
    for (const key of ['recognisability', 'original_views', 'original_url', 'source_status', 'audio_risk', 'est_credits', 'season', 'checks', 'source_candidates'] as const) {
      expect([key, picks.some((p) => p[key] != null)]).toEqual([key, true]);
      expect([key, picks.some((p) => p[key] == null)]).toEqual([key, true]);
    }
  });
});
