import { describe, expect, it } from 'vitest';
import {
  clipCode,
  formatAge,
  formatCountdown,
  formatCredits,
  formatViews,
  isoToLondonWall,
  londonDayKey,
  londonTime,
  londonWallToIso,
  outlierBadge,
} from './format';

describe('formatCredits', () => {
  it('groups thousands and appends the unit', () => {
    expect(formatCredits(1234)).toBe('1,234 cr');
    expect(formatCredits(0)).toBe('0 cr');
    expect(formatCredits(6000)).toBe('6,000 cr');
  });
  it('rounds fractional credits and shows a dash for no value', () => {
    expect(formatCredits(159.6)).toBe('160 cr');
    expect(formatCredits(null)).toBe('—');
    expect(formatCredits(undefined)).toBe('—');
  });
});

describe('outlierBadge', () => {
  it('calls 3x and above a hit (the pre-registered bar)', () => {
    expect(outlierBadge(3)).toEqual({ label: '3.0×', tone: 'hit' });
    expect(outlierBadge(12.34)).toEqual({ label: '12.3×', tone: 'hit' });
  });
  it('calls 1.5x and above good, 0.7x and below weak, the rest neutral', () => {
    expect(outlierBadge(1.5).tone).toBe('good');
    expect(outlierBadge(2.99).tone).toBe('good');
    expect(outlierBadge(1.49).tone).toBe('neutral');
    expect(outlierBadge(0.71).tone).toBe('neutral');
    expect(outlierBadge(0.7).tone).toBe('weak');
    expect(outlierBadge(0).tone).toBe('weak');
  });
  it('shows a dash when there is no result yet', () => {
    expect(outlierBadge(null)).toEqual({ label: '—', tone: 'none' });
    expect(outlierBadge(undefined)).toEqual({ label: '—', tone: 'none' });
    expect(outlierBadge(Number.NaN)).toEqual({ label: '—', tone: 'none' });
  });
  it('drops the decimal for big outliers', () => {
    expect(outlierBadge(1393).label).toBe('1,393×');
  });
});

describe('formatViews', () => {
  it('compacts to K and M with one decimal', () => {
    expect(formatViews(43_400_000)).toBe('43.4M');
    expect(formatViews(349_700)).toBe('349.7K');
    expect(formatViews(2_000_000)).toBe('2M');
    expect(formatViews(812)).toBe('812');
    expect(formatViews(null)).toBe('—');
  });
});

describe('formatCountdown', () => {
  it('reads hours and minutes until a moment', () => {
    const now = Date.UTC(2026, 9, 6, 14, 48);
    expect(formatCountdown(Date.UTC(2026, 9, 6, 18, 0), now)).toBe('3h 12m');
    expect(formatCountdown(Date.UTC(2026, 9, 6, 15, 0), now)).toBe('12m');
    expect(formatCountdown(Date.UTC(2026, 9, 6, 14, 48, 30), now)).toBe('now');
    expect(formatCountdown(Date.UTC(2026, 9, 8, 18, 0), now)).toBe('2d 3h');
  });
  it('says gone for a moment in the past', () => {
    const now = Date.UTC(2026, 9, 6, 19, 0);
    expect(formatCountdown(Date.UTC(2026, 9, 6, 18, 0), now)).toBe('gone');
  });
});

describe('London time', () => {
  it('formats the wall clock in Europe/London, BST and GMT alike', () => {
    expect(londonTime('2026-10-06T18:00:00Z')).toBe('19:00'); // BST
    expect(londonTime('2026-11-03T19:00:00Z')).toBe('19:00'); // GMT
  });
  it('keys the London calendar day, not the UTC one', () => {
    expect(londonDayKey('2026-10-06T23:30:00Z')).toBe('2026-10-07');
    expect(londonDayKey('2026-11-03T23:30:00Z')).toBe('2026-11-03');
  });
});

describe('clipCode', () => {
  it('is a short flight-number style code: character prefix and the id head', () => {
    expect(clipCode('3f9a2c41-0000-4000-8000-000000000000', 'biscuit')).toBe('BSC 3F9A');
    expect(clipCode('a1b2c3d4-0000-4000-8000-000000000000', 'reginald')).toBe('RGN A1B2');
  });
  it('falls back to the first three letters for an unknown character', () => {
    expect(clipCode('0bad0000-0000-4000-8000-000000000000', 'outsider')).toBe('OUT 0BAD');
  });
});

describe('London wall time for the schedule picker', () => {
  it('reads a datetime-local value as London time, BST and GMT', () => {
    expect(londonWallToIso('2026-10-06T19:00')).toBe('2026-10-06T18:00:00.000Z');
    expect(londonWallToIso('2026-11-03T19:00')).toBe('2026-11-03T19:00:00.000Z');
  });
  it('writes a moment back as a London datetime-local value', () => {
    expect(isoToLondonWall('2026-10-06T18:00:00Z')).toBe('2026-10-06T19:00');
    expect(isoToLondonWall('2026-11-03T19:30:00Z')).toBe('2026-11-03T19:30');
  });
  it('refuses a malformed value', () => {
    expect(() => londonWallToIso('tomorrow')).toThrow();
  });
});

describe('formatAge', () => {
  const now = Date.parse('2026-10-06T12:00:00Z');
  const ago = (ms: number) => new Date(now - ms).toISOString();
  it('says how long ago, in the largest two units that matter', () => {
    expect(formatAge(ago(20_000), now)).toBe('just now');
    expect(formatAge(ago(30 * 60_000), now)).toBe('30m ago');
    expect(formatAge(ago(2 * 3_600_000 + 5 * 60_000), now)).toBe('2h ago');
    expect(formatAge(ago(26 * 3_600_000), now)).toBe('1d 2h ago');
    expect(formatAge(ago(3 * 86_400_000), now)).toBe('3d ago');
  });
  it('a moment in the future (clock skew) is just now; no moment is a dash', () => {
    expect(formatAge(new Date(now + 60_000).toISOString(), now)).toBe('just now');
    expect(formatAge(null, now)).toBe('—');
  });
});
