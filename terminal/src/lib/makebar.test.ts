// The tick-and-make bar (spec 5.2, Review Focus 5): never fires without the confirm; the confirm's total, budget left and cap.
import { describe, expect, it } from 'vitest';
import {
  MAKE_BAR_START, confirmFacts, creditsWords, idsToSend, liveSelection, makeBarLabel, makeBarReducer, resultsHeading, type MakeBarState,
} from './makebar';
import type { DropCard, TrackerRow } from './types';

const card = (over: Partial<DropCard> = {}): DropCard => ({ state: 'ready', character_by: 'owner', window: { start_s: 0, length_s: 8 }, seconds: 8, credits: 91, ...over });
const row = (id: string, drop: DropCard | null): Pick<TrackerRow, 'pick_id' | 'drop_card'> => ({ pick_id: id, drop_card: drop });
const budget = (cap: number, committed: number, kill = false) => ({ cap, committed, kill_switch: kill });
const ok = (pickId: string) => ({ pickId, ok: true, dispatched: true, message: 'Sent: making starts now' });

describe('the bar never fires without the confirm', () => {
  it('opens the confirm with the ticked clips, each once, and sends exactly those after the confirm', () => {
    const open = makeBarReducer(MAKE_BAR_START, { type: 'open', ids: ['a', 'b', 'a'] });
    expect(open).toEqual({ step: 'confirm', ids: ['a', 'b'] });
    expect(idsToSend(MAKE_BAR_START, open)).toEqual([]); // opening sends nothing
    const sending = makeBarReducer(open, { type: 'send' });
    expect(sending).toEqual({ step: 'sending', ids: ['a', 'b'] });
    expect(idsToSend(open, sending)).toEqual(['a', 'b']);
  });

  it('a send while ticking, sending or showing results changes nothing and sends nothing', () => {
    const states: MakeBarState[] = [MAKE_BAR_START, { step: 'sending', ids: ['a'] }, { step: 'done', results: [ok('a')] }];
    for (const s of states) {
      const next = makeBarReducer(s, { type: 'send' });
      expect(next).toBe(s);
      expect(idsToSend(s, next)).toEqual([]);
    }
  });

  it('does not open with nothing ticked, nor while sending', () => {
    expect(makeBarReducer(MAKE_BAR_START, { type: 'open', ids: [] })).toBe(MAKE_BAR_START);
    const sending: MakeBarState = { step: 'sending', ids: ['a'] };
    expect(makeBarReducer(sending, { type: 'open', ids: ['b'] })).toBe(sending);
  });

  it('cancel goes back to ticking; the results stay until closed; a new open from the results asks again', () => {
    const confirm = makeBarReducer(MAKE_BAR_START, { type: 'open', ids: ['a'] });
    expect(makeBarReducer(confirm, { type: 'cancel' })).toEqual(MAKE_BAR_START);
    const done = makeBarReducer({ step: 'sending', ids: ['a'] }, { type: 'finished', results: [ok('a')] });
    expect(done).toEqual({ step: 'done', results: [ok('a')] });
    expect(makeBarReducer(done, { type: 'cancel' })).toBe(done);
    expect(makeBarReducer(done, { type: 'close' })).toEqual(MAKE_BAR_START);
    expect(makeBarReducer(done, { type: 'open', ids: ['b'] })).toEqual({ step: 'confirm', ids: ['b'] });
    // a late result while ticking is ignored
    expect(makeBarReducer(MAKE_BAR_START, { type: 'finished', results: [ok('a')] })).toBe(MAKE_BAR_START);
  });
});

describe('confirmFacts', () => {
  const rows = [
    row('a', card()), // 91
    row('b', card({ seconds: 12, credits: 135, adjust: { length_s: 10 } })), // its own Adjust: ceil(10 x 11) + 3 = 113
    row('c', card({ state: 'checking', credits: undefined })), // no price yet
  ];

  it('totals the ticked clips at the price their rows show, with the month left and after', () => {
    const f = confirmFacts(rows, ['a', 'b', 'c'], budget(6000, 1200));
    expect(f).toMatchObject({ count: 2, cap: 6000, left: 4800, blocked: null });
    expect(f.credits).toBe(91 + 113);
    expect(f.leftAfter).toBe(4800 - 204);
  });

  it('blocks past what is left of the cap, with the kill switch on, or with nothing priced', () => {
    expect(confirmFacts(rows, ['a'], budget(6000, 5950)).blocked).toBe('That is more than the 50 credits left this month. Untick some clips.');
    expect(confirmFacts(rows, ['a'], budget(6000, 7000)).left).toBe(0);
    expect(confirmFacts(rows, ['a'], budget(6000, 0, true)).blocked).toMatch(/^The kill switch is on/);
    expect(confirmFacts(rows, ['c'], budget(6000, 0)).blocked).toMatch(/^None of these clips has a price yet/);
    expect(confirmFacts(rows, ['a'], budget(6000, 5909)).blocked).toBeNull(); // exactly what is left is fine
  });

  it('without a budget it says nothing about the month and lets him go on', () => {
    expect(confirmFacts(rows, ['a'], null)).toEqual({ count: 1, credits: 91, left: null, cap: null, leftAfter: null, blocked: null });
  });
});

describe('the bar label and the live selection', () => {
  it('says the count and the credits, in the spec words', () => {
    expect(makeBarLabel({ count: 3, credits: 291 })).toBe('Make 3 selected · 291 credits');
    expect(makeBarLabel({ count: 1, credits: 1234 })).toBe('Make 1 selected · 1,234 credits');
    expect(makeBarLabel({ count: 0, credits: 0 })).toBe('Make selected');
    expect(creditsWords(1)).toBe('1 credit');
  });
  it('heads the results with what was sent and what was refused, each clip counted', () => {
    const no = { ok: false };
    const yes = { ok: true };
    expect(resultsHeading([yes, yes, yes])).toBe('3 clips sent to be made');
    expect(resultsHeading([yes])).toBe('1 clip sent to be made');
    expect(resultsHeading([yes, no, yes])).toBe('2 clips sent to be made, 1 refused');
    expect(resultsHeading([no, no])).toBe('Nothing was sent: 2 refused');
    expect(resultsHeading([])).toBe('Nothing was sent');
  });
  it('keeps only the ticked clips that can still be made, each once, in order', () => {
    expect(liveSelection(['c', 'a', 'x', 'a'], new Set(['a', 'b', 'c']))).toEqual(['c', 'a']);
    expect(liveSelection(new Set<string>(), new Set(['a']))).toEqual([]);
  });
});
