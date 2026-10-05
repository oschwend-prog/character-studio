// The analyst's data on a pick card: age, velocity, reactions, saturation, the words on the card, and the settings copy.
// Pure rules, tested without a browser; the cases of velocity, engagement and saturation are the ones studio/favorites.py is tested with.
import { readFileSync } from 'node:fs';
import { describe, expect, it } from 'vitest';
import {
  ageDays, clipCheckChips, engagementRates, formatRate, parseMoment, pickFacts, pickVelocity, postedLabel, saturationScore,
  velocityLabel, velocityPerDay,
} from './analyst';
import parity from './parity-cases.json';
import * as scanConfig from './scanConfig';
import type { ClipAnalysis } from './types';

const NOW = Date.parse(parity.now);
const DAY = 86_400_000;
const ago = (days: number) => new Date(NOW - days * DAY).toISOString();

describe('age', () => {
  it('is the days since the post date, a fraction included, and null when it is unknown or unreadable', () => {
    expect(ageDays(ago(6), NOW)).toBeCloseTo(6, 6);
    expect(ageDays(ago(0.5), NOW)).toBeCloseTo(0.5, 6);
    expect(ageDays('2026-10-01', NOW)).toBeCloseTo(4.375, 6); // a plain date is midnight UTC, like Python's
    expect(ageDays(null, NOW)).toBeNull();
    expect(ageDays('not a date', NOW)).toBeNull();
    expect(ageDays('', NOW)).toBeNull();
  });

  it('reads a date-time with no offset as UTC, never as the browser’s own zone', () => {
    expect(parseMoment('2026-10-04T09:00:00')).toBe(Date.parse('2026-10-04T09:00:00Z'));
    expect(parseMoment('2026-10-04 09:00')).toBe(Date.parse('2026-10-04T09:00:00Z'));
    expect(parseMoment('2026-10-04T09:00:00+01:00')).toBe(Date.parse('2026-10-04T08:00:00Z'));
  });

  it('is said in plain words: today, N days ago, months, years', () => {
    expect(postedLabel(0.4)).toBe('posted today');
    expect(postedLabel(1)).toBe('posted 1 day ago');
    expect(postedLabel(6.2)).toBe('posted 6 days ago');
    expect(postedLabel(59)).toBe('posted 59 days ago');
    expect(postedLabel(120)).toBe('posted 4 months ago');
    expect(postedLabel(400)).toBe('posted 1 year ago');
    expect(postedLabel(800)).toBe('posted 2 years ago');
    expect(postedLabel(null)).toBeNull();
  });
});

describe('velocity (the same cases as studio.favorites.velocity_per_day)', () => {
  it('agrees with every shared case', () => {
    expect(parity.velocity.length).toBeGreaterThanOrEqual(5);
    for (const c of parity.velocity) expect([JSON.stringify(c), velocityPerDay(c.views, c.days_ago)]).toEqual([JSON.stringify(c), c.expect]);
  });

  it('divides a clip posted hours ago by one day, not by a fraction of one', () => {
    expect(velocityPerDay(1_000_000, 0.1)).toBe(1_000_000);
    expect(velocityPerDay(-5, 3)).toBeNull();
    expect(velocityPerDay(Number.NaN, 3)).toBeNull();
  });

  it('prefers the one stored when the pick was filed, else works it out from the views and the age', () => {
    expect(pickVelocity({ velocity: 123_456, views: 3_100_000, posted_at: ago(10) }, NOW)).toBe(123_456);
    expect(pickVelocity({ velocity: null, views: 3_100_000, posted_at: ago(10) }, NOW)).toBe(310_000);
    expect(pickVelocity({ views: 3_100_000, posted_at: null }, NOW)).toBeNull();
    expect(velocityLabel(310_000)).toBe('≈310K views/day');
    expect(velocityLabel(1_240_000)).toBe('≈1.2M views/day');
    expect(velocityLabel(null)).toBeNull();
  });
});

describe('engagement (the same cases as studio.favorites.engagement_rates)', () => {
  it('agrees with every shared case', () => {
    expect(parity.engagement.length).toBeGreaterThanOrEqual(6);
    for (const c of parity.engagement) {
      const got = engagementRates(c.engagement, c.views);
      if (c.expect == null) expect([JSON.stringify(c), got]).toEqual([JSON.stringify(c), null]);
      else {
        expect(got?.engagement_rate).toBeCloseTo(c.expect.engagement_rate, 9);
        if (c.expect.share_rate == null) expect(got?.share_rate).toBeNull();
        else expect(got?.share_rate).toBeCloseTo(c.expect.share_rate, 9);
      }
    }
  });

  it('formats a rate with one decimal under 10% and none above', () => {
    expect([formatRate(0.048), formatRate(0.12), formatRate(0.005), formatRate(0.1)]).toEqual(['4.8%', '12%', '0.5%', '10%']);
  });
});

describe('saturation (the same table as studio.favorites.saturation_score)', () => {
  it('agrees with every shared case', () => {
    for (const c of parity.saturation) expect([c.count, saturationScore(c.count)]).toEqual([c.count, c.expect]);
  });
  it('refuses anything that is not a whole number of 0 or more', () => {
    for (const bad of [-1, 2.5, Number.NaN]) expect(() => saturationScore(bad)).toThrow();
  });
});

describe('the clip check row', () => {
  const clean: ClipAnalysis = {
    people_count: 1, main_subject: 'a dachshund in a tracksuit', camera: 'static', watermark: false, overlay: false, minors: false,
    best_window: { start_s: 2.5, end_s: 10 }, bpm: 112.5,
  };
  it('says what was found, as short chips with a tone', () => {
    expect(clipCheckChips(clean)).toEqual([
      { text: '1 person', tone: 'plain' },
      { text: 'a dachshund in a tracksuit', tone: 'plain' },
      { text: 'Static camera', tone: 'ok' },
      { text: 'No watermark', tone: 'ok' },
      { text: 'No text overlay', tone: 'ok' },
      { text: 'No children', tone: 'ok' },
      { text: 'Best 2.5-10 s (7.5 s)', tone: 'plain' },
      { text: '113 bpm', tone: 'plain' },
    ]);
  });
  it('flags a watermark, burned-in text, a child and a camera that is not static', () => {
    const chips = clipCheckChips({ ...clean, people_count: 0, camera: 'handheld', watermark: true, overlay: true, minors: true, best_window: null, bpm: null, main_subject: undefined });
    expect(chips).toEqual([
      { text: 'No people', tone: 'plain' },
      { text: 'Handheld camera', tone: 'warn' },
      { text: 'Watermark or handle', tone: 'bad' },
      { text: 'Text on screen', tone: 'bad' },
      { text: 'Child visible', tone: 'bad' },
    ]);
  });
});

describe('pickFacts (everything the card says beyond its top line)', () => {
  it('collects age, velocity, reactions, saturation, the matched traits, why and the check', () => {
    const f = pickFacts(
      {
        views: 3_100_000, posted_at: ago(10), velocity: null, engagement: { likes: 90_000, shares: 31_000 }, saturation_count: 3,
        trait_matches: ['slick upright dance', ' ', 'hits every beat'], why: '  One animal, static camera.  ',
        analysis: { people_count: 1, camera: 'static', watermark: false, overlay: false, minors: false, notes: ' one cut at 9 s ' },
      },
      NOW,
    );
    expect(f.posted).toBe('posted 10 days ago');
    expect(f.velocity).toBe('≈310K views/day');
    expect(f.engagement).toBe('3.9% engaged');
    expect(f.shares).toBe('1.0% shares');
    expect(f.saturation).toBe('3 similar videos this week');
    expect(f.matches).toEqual(['slick upright dance', 'hits every beat']);
    expect(f.why).toBe('One animal, static camera.');
    expect(f.check?.map((c) => c.text)).toContain('Static camera');
    expect(f.checkNotes).toBe('one cut at 9 s');
  });

  it('leaves out what is not known and never invents a number', () => {
    const f = pickFacts({ views: null }, NOW);
    expect(f).toEqual({ posted: null, velocity: null, engagement: null, shares: null, saturation: null, matches: [], why: null, check: null, checkNotes: null });
    expect(pickFacts({ views: 500, saturation_count: 0 }, NOW).saturation).toBe('no copies this week');
    expect(pickFacts({ views: 500, saturation_count: 1 }, NOW).saturation).toBe('1 similar video this week');
  });
});

// ---- scanConfig.ts is a copy of config/scan.json: the two must not drift apart ---------------------------------------------------------------

interface ScanFile {
  tier_rules: Record<string, unknown>; saturation_steps: unknown; defaults: unknown; budget: Record<string, unknown>; access: unknown;
  video_requirements: unknown; global_reject_rules: unknown;
  characters: Record<string, { audienceQuery: string; rotation: unknown; fit_rules?: unknown; _status?: string }>;
}
const scan = JSON.parse(readFileSync(new URL('../../../config/scan.json', import.meta.url), 'utf8')) as ScanFile;
const plain = (o: Record<string, unknown>) => Object.fromEntries(Object.entries(o).filter(([k]) => !k.startsWith('_')));

describe('scanConfig.ts equals config/scan.json', () => {
  it('has the same tier rule, saturation table, defaults, budget, access list and requirements', () => {
    expect(scanConfig.TIER_RULES).toEqual(plain(scan.tier_rules));
    expect(scanConfig.SATURATION_STEPS).toEqual(scan.saturation_steps);
    expect(scanConfig.SCAN_DEFAULTS).toEqual(scan.defaults);
    expect(scanConfig.SCAN_BUDGET).toEqual(plain(scan.budget));
    expect(scanConfig.SCAN_ACCESS).toEqual(scan.access);
    expect(scanConfig.VIDEO_REQUIREMENTS).toEqual(scan.video_requirements);
    expect(scanConfig.GLOBAL_REJECT_RULES).toEqual(scan.global_reject_rules);
  });

  it('has the same themes, queries, audience and fit rules for every character', () => {
    expect(Object.keys(scanConfig.SCAN_CHARACTERS).sort()).toEqual(Object.keys(scan.characters).sort());
    for (const [slug, c] of Object.entries(scan.characters)) {
      const mine = scanConfig.SCAN_CHARACTERS[slug];
      expect([slug, mine.audienceQuery]).toEqual([slug, c.audienceQuery]);
      expect([slug, mine.rotation]).toEqual([slug, c.rotation]);
      expect([slug, mine.fit_rules]).toEqual([slug, c.fit_rules ?? []]);
      expect([slug, mine.status]).toEqual([slug, c._status]);
    }
  });
});
