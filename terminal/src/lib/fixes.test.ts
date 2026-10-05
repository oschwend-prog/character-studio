// Fix round 1 (Task 15 review): queue position, approve-all loop, standalone sign-in, autopilot copy,
// muted-text contrast.
import { readFileSync } from 'node:fs';
import { describe, expect, it } from 'vitest';
import { approveAll, autopilotState, captionEdit, focusToApply, queuePosition, selectApprovable } from './rules';
import { isStandalone, normaliseOtpCode } from './auth';

describe('queue position survives refreshes (the deep-linked clip no longer snaps back)', () => {
  const ids = ['a', 'b', 'c'];
  it('keeps the clip being viewed wherever it sits after a reload', () => {
    expect(queuePosition(ids, 'b', 0)).toBe(1);
    expect(queuePosition(['x', 'a', 'b', 'c'], 'b', 1)).toBe(2); // a new clip arrived in front
  });
  it('shows the clip that took its place when the viewed one left the queue', () => {
    expect(queuePosition(['a', 'c'], 'b', 1)).toBe(1);
    expect(queuePosition(['a'], 'c', 2)).toBe(0);
    expect(queuePosition([], 'c', 2)).toBe(0);
  });
  it('starts at the first clip with nothing chosen', () => {
    expect(queuePosition(ids, null, 0)).toBe(0);
  });
});

describe('the deep link is applied once, not on every reload', () => {
  it('jumps to a new link, then never again for the same link', () => {
    expect(focusToApply('b', null, ['a', 'b'])).toBe('b');
    expect(focusToApply('b', 'b', ['a', 'b'])).toBeNull(); // a refresh after the owner pressed Next
    expect(focusToApply('c', 'b', ['a', 'b'])).toBeNull(); // not (yet) in the queue
    expect(focusToApply(null, null, ['a'])).toBeNull();
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
