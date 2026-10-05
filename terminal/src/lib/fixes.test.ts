// Fix round 1 (Task 15 review): queue position, approve-all loop, standalone sign-in, autopilot copy,
// muted-text contrast.
import { readFileSync } from 'node:fs';
import { describe, expect, it } from 'vitest';
import { approveAll, autopilotState, captionEdit, nextCurrentId, selectApprovable } from './rules';
import { isStandalone, normaliseOtpCode } from './auth';

describe('the queue pager: one decision for which clip is on screen', () => {
  const ids = ['a', 'b', 'c'];
  it('first render with a deep link to a non-first clip shows that clip', () => {
    expect(nextCurrentId({ ids, currentId: null, focus: 'b', appliedFocus: null, lastIndex: 0 })).toEqual({ id: 'b', appliedFocus: 'b' });
    expect(nextCurrentId({ ids, currentId: null, focus: 'c', appliedFocus: null, lastIndex: 0 })).toEqual({ id: 'c', appliedFocus: 'c' });
  });
  it('a pending deep link waits for the queue to load, then wins', () => {
    expect(nextCurrentId({ ids: [], currentId: null, focus: 'c', appliedFocus: null, lastIndex: 0 })).toEqual({ id: null, appliedFocus: null });
    expect(nextCurrentId({ ids, currentId: 'a', focus: 'c', appliedFocus: null, lastIndex: 0 })).toEqual({ id: 'c', appliedFocus: 'c' });
  });
  it('a refresh keeps the clip being viewed once the link was applied (no snap back)', () => {
    expect(nextCurrentId({ ids, currentId: 'c', focus: 'b', appliedFocus: 'b', lastIndex: 0 })).toEqual({ id: 'c', appliedFocus: 'b' });
    expect(nextCurrentId({ ids: ['x', ...ids], currentId: 'c', focus: null, appliedFocus: null, lastIndex: 0 }).id).toBe('c');
  });
  it('nothing chosen starts at the first clip; empty is null', () => {
    expect(nextCurrentId({ ids, currentId: null, focus: null, appliedFocus: null, lastIndex: 0 }).id).toBe('a');
    expect(nextCurrentId({ ids, currentId: null, focus: null, appliedFocus: null, lastIndex: 2 }).id).toBe('a'); // no clip was being viewed
    expect(nextCurrentId({ ids: [], currentId: 'b', focus: null, appliedFocus: null, lastIndex: 1 }).id).toBeNull();
    expect(nextCurrentId({ ids: [], currentId: null, focus: null, appliedFocus: null, lastIndex: 0 }).id).toBeNull();
  });
  it('a removed clip hands over to the clip that took its place (approve, reject, regenerate or Realtime)', () => {
    // approving clip 2 of 3: the former clip 3 is now clip 2 of 2
    const after = nextCurrentId({ ids: ['a', 'c'], currentId: 'b', focus: null, appliedFocus: null, lastIndex: 1 });
    expect(after.id).toBe('c');
    expect(['a', 'c'].indexOf(after.id as string) + 1).toBe(2);
    // the first clip leaves: the next one is first now
    expect(nextCurrentId({ ids: ['b', 'c'], currentId: 'a', focus: null, appliedFocus: null, lastIndex: 0 }).id).toBe('b');
  });
  it('removing the last clip lands on the new last clip', () => {
    expect(nextCurrentId({ ids: ['a', 'b'], currentId: 'c', focus: null, appliedFocus: null, lastIndex: 2 }).id).toBe('b');
    expect(nextCurrentId({ ids: ['a'], currentId: 'b', focus: null, appliedFocus: null, lastIndex: 5 }).id).toBe('a'); // clamped
  });
  it('a deep link that was applied and then removed also hands over by position, not to the first', () => {
    expect(nextCurrentId({ ids: ['a', 'c'], currentId: 'b', focus: 'b', appliedFocus: 'b', lastIndex: 1 }).id).toBe('c');
  });
  it('a pending deep link still wins over the position, and a present current clip over both', () => {
    expect(nextCurrentId({ ids, currentId: 'a', focus: 'c', appliedFocus: null, lastIndex: 0 }).id).toBe('c');
    expect(nextCurrentId({ ids, currentId: 'b', focus: null, appliedFocus: null, lastIndex: 2 }).id).toBe('b');
  });
  it('a new deep link (a different clip) wins again', () => {
    expect(nextCurrentId({ ids, currentId: 'c', focus: 'a', appliedFocus: 'b', lastIndex: 0 })).toEqual({ id: 'a', appliedFocus: 'a' });
  });
});

describe('approve all keeps going past refusals and counts', () => {
  it('approves every id in order, collects refusals, never stops early', async () => {
    const seen: string[] = [];
    const backend = {
      approveClip: async (id: string) => {
        seen.push(id);
        if (id === 'b') throw new Error('no connected account for reginald');
      },
    };
    const r = await approveAll(backend, ['a', 'b', 'c']);
    expect(seen).toEqual(['a', 'b', 'c']);
    expect(r.approved).toBe(2);
    expect(r.refused).toEqual(['no connected account for reginald']);
    expect(r.summary).toBe('2 approved, 1 refused: no connected account for reginald');
  });
  it('says plainly when all went through', async () => {
    const r = await approveAll({ approveClip: async () => undefined }, ['a', 'b']);
    expect(r.summary).toBe('2 approved');
  });
  it('skips a clip the database says is blocked, with its reason', () => {
    const r = selectApprovable([
      { id: 'a', state: 'awaiting_approval', master_path: 'a.mp4', targets: [{}], blocked_reason: null },
      { id: 'b', state: 'awaiting_approval', master_path: 'b.mp4', targets: [{}], blocked_reason: 'no account may take this dropin clip' },
    ]);
    expect(r.ids).toEqual(['a']);
    expect(r.skipped).toEqual([{ id: 'b', reason: 'no account may take this dropin clip' }]);
  });
});

describe('an emptied caption or hook is never sent as an empty string', () => {
  it('sends null when unchanged or emptied, the trimmed text when changed', () => {
    expect(captionEdit('same', 'same')).toBeNull();
    expect(captionEdit('   ', 'old caption')).toBeNull();
    expect(captionEdit('', null)).toBeNull();
    expect(captionEdit(' new one ', 'old')).toBe('new one');
  });
});

describe('sign-in from the installed app', () => {
  it('detects the Home Screen app (display-mode standalone, or iOS navigator.standalone)', () => {
    expect(isStandalone({ matchMedia: (q: string) => ({ matches: q === '(display-mode: standalone)' }) })).toBe(true);
    expect(isStandalone({ matchMedia: () => ({ matches: false }), navigator: { standalone: true } })).toBe(true);
    expect(isStandalone({ matchMedia: () => ({ matches: false }), navigator: {} })).toBe(false);
  });
  it('accepts the emailed code with spaces or dashes, 6 to 10 digits', () => {
    expect(normaliseOtpCode(' 123 456 ')).toBe('123456');
    expect(normaliseOtpCode('123-456')).toBe('123456');
    expect(normaliseOtpCode('12345')).toBeNull();
    expect(normaliseOtpCode('12345a')).toBeNull();
    expect(normaliseOtpCode('12345678')).toBe('12345678');
  });
});

describe('autopilot copy: posting is automatic only when every connected channel of the character is on', () => {
  it('on, with a sibling channel still on approval, says clips still wait', () => {
    const s = autopilotState({ mode: 'auto', approved_posts: 7 }, { characterName: 'Biscuit', allConnectedAuto: false });
    expect(s.reason).toBe('On, but Biscuit clips still wait for you until every connected Biscuit channel is on autopilot');
  });
  it('on everywhere says clips post without asking', () => {
    const s = autopilotState({ mode: 'auto', approved_posts: 7 }, { characterName: 'Biscuit', allConnectedAuto: true });
    expect(s.reason).toBe('On: Biscuit clips that pass QA post at the next slot without asking');
  });
  it('unlocked but off explains the all-channels rule', () => {
    const s = autopilotState({ mode: 'approval', approved_posts: 7 }, { characterName: 'Biscuit', allConnectedAuto: false });
    expect(s.reason).toBe('Unlocked. Posting is automatic only when every connected Biscuit channel is on autopilot');
  });
});

describe('muted text meets WCAG AA on every surface it is used on', () => {
  const css = readFileSync(new URL('../styles.css', import.meta.url), 'utf8');
  const token = (name: string) => {
    const m = new RegExp(`--${name}:\\s*(#[0-9a-fA-F]{6})`).exec(css);
    if (!m) throw new Error(`no --${name}`);
    return m[1];
  };
  const lum = (hex: string) => {
    const [r, g, b] = [1, 3, 5].map((i) => parseInt(hex.slice(i, i + 2), 16) / 255).map((c) =>
      c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4,
    );
    return 0.2126 * r + 0.7152 * g + 0.0722 * b;
  };
  const ratio = (a: string, b: string) => {
    const [hi, lo] = [lum(a), lum(b)].sort((x, y) => y - x);
    return (hi + 0.05) / (lo + 0.05);
  };
  for (const ground of ['board', 'panel', 'panel-2', 'tile', 'tile-top']) {
    it(`ink-3 on ${ground} is at least 4.5:1`, () => {
      expect(ratio(token('ink-3'), token(ground))).toBeGreaterThanOrEqual(4.5);
    });
  }
});

// ---- final fix wave: copy that states what the rules now do -------------------------------------------

import { KILL_SWITCH_COPY, SCHEDULE_NOTE, SLOT_RULE } from './rules';

describe('copy states the real rules', () => {
  it('the slot rule says one free day per channel, not "the next slot" (migration 0006 free_slot)', () => {
    expect(SLOT_RULE).toMatch(/first free/i);
    expect(SLOT_RULE).toMatch(/no post/i);
    expect(SLOT_RULE).not.toMatch(/3rd clip/);
  });
  it('the schedule note keeps the 2-a-day cap and says a chosen time posts within about 3 hours', () => {
    expect(SCHEDULE_NOTE).toMatch(/2 posts per channel per day/);
    expect(SCHEDULE_NOTE).toMatch(/within about 3 hours/);
  });
  it('the kill switch stops posting as well as spend (the spec: "stops generation and posting")', () => {
    expect(KILL_SWITCH_COPY.stopButton).toBe('Stop all new spend and posting');
    expect(KILL_SWITCH_COPY.on).toMatch(/nothing is generated or posted/i);
    expect(KILL_SWITCH_COPY.today).toMatch(/nothing is generated or posted/i);
    expect(KILL_SWITCH_COPY.toastOn).toMatch(/nothing is generated or posted/i);
    for (const text of Object.values(KILL_SWITCH_COPY)) expect(text).not.toMatch(/posting of approved clips carries on/i);
  });
  it('the pages use the shared copy, not their own wording', () => {
    const read = (p: string) => readFileSync(new URL(p, import.meta.url), 'utf8');
    expect(read('../pages/Budget.tsx')).toContain('KILL_SWITCH_COPY');
    expect(read('../pages/Today.tsx')).toContain('KILL_SWITCH_COPY.today');
    expect(read('../pages/Queue.tsx')).toContain('SCHEDULE_NOTE');
    expect(read('../pages/Budget.tsx')).not.toMatch(/Posting of approved clips carries on/);
    expect(read('../pages/Today.tsx')).not.toMatch(/no new clips are generated/);
  });
});

describe('sign-in never creates an account (the only owner is already in)', () => {
  it('Login asks for an OTP with shouldCreateUser: false', () => {
    const login = readFileSync(new URL('../Login.tsx', import.meta.url), 'utf8');
    expect(login).toMatch(/signInWithOtp\(\{[\s\S]*shouldCreateUser: false/);
  });
});
