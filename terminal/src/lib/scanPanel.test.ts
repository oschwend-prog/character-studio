// "How we scan": the words of the panel come from the same numbers the scanner and the categories use.
import { describe, expect, it } from 'vitest';
import { budgetView, filterLines, lastScanView, parseAudience, scanCharacters, tierExamples, tierRuleLines } from './scanPanel';
import { CREDITS, TIER_LABELS, TIERS, scannerStatus } from './rules';
import { SCAN_BUDGET, SCAN_CHARACTERS, TIER_RULES } from './scanConfig';
import type { RunRow } from './types';

const NOW = Date.parse('2026-10-05T09:00:00Z');
const DAY = 86_400_000;
const ago = (days: number) => new Date(NOW - days * DAY).toISOString();

describe('the category rule on the panel', () => {
  it('lists the rules in the order they apply, ending with the fallback', () => {
    expect(tierRuleLines().map((l) => l.id)).toEqual(['gallery', 'iconic', 'viral_now', 'rising', 'fallback']);
    expect(tierRuleLines().slice(0, 4).map((l) => l.label)).toEqual(['Ready to drop in', 'Broke the internet', 'Viral now', 'Up and coming']);
  });

  it('spells out the exact numbers of the shared rule', () => {
    const rule = Object.fromEntries(tierRuleLines().map((l) => [l.id, l.rule]));
    expect(rule.iconic).toBe('Older than 180 days, or 50M views or more');
    expect(rule.viral_now).toBe('Posted within 21 days with an outlier of 20× or more, or climbing at 100K views a day or more');
    expect(rule.rising).toBe('Posted within 7 days with an outlier of 5× or more');
    expect(rule.fallback).toBe('Viral now up to 30 days old, Broke the internet after that (a video with no post date counts as Viral now)');
    expect(rule.gallery).toContain('Genjutsu');
  });

  it('is worded from TIER_RULES, so a changed number changes the words', () => {
    expect(tierRuleLines()[1].rule).toContain(String(TIER_RULES.iconic_min_age_days));
    expect(tierRuleLines()[2].rule).toContain(String(TIER_RULES.viral_now_max_age_days));
    expect(tierRuleLines()[3].rule).toContain(String(TIER_RULES.rising_max_age_days));
  });
});

describe('what is scanned', () => {
  it('says the filters in the owner’s words', () => {
    expect(filterLines()).toEqual([
      'Posted in the last 14 days',
      '200K views or more',
      'Outlier score 5× or more: views against the creator’s own median',
      '30 seconds or shorter',
      'Up to 20 results per platform (Instagram Reels and TikTok)',
      'English descriptions',
      'One result per creator',
    ]);
  });

  it('reads the audience of a character out of its audience query', () => {
    expect(parseAudience(SCAN_CHARACTERS.biscuit.audienceQuery)).toEqual({
      region: 'US/UK English-speaking',
      audience: 'dog lovers and Gen Z/millennials 16-40 who watch cute pet and dance content',
    });
    expect(parseAudience('nothing useful')).toEqual({ region: null, audience: null });
  });

  it('gives each rostered character its themes and queries, and leaves out one with no scan settings', () => {
    const roster = [{ slug: 'biscuit', name: 'Biscuit' }, { slug: 'reginald', name: 'Reginald' }, { slug: 'nobody', name: 'Nobody' }];
    const views = scanCharacters(roster);
    expect(views.map((v) => v.slug)).toEqual(['biscuit', 'reginald']);
    expect(views[0].themes.map((t) => t.theme)).toEqual(['skilled upright dance', 'dog leads the dancers', 'stare, then hits every beat', 'pet with a human job']);
    expect(views[1].themes[0]).toMatchObject({ theme: 'deadpan at work', embeddingType: 'concept' });
    expect(views.every((v) => v.inactive === null && v.themes.every((t) => t.query.length > 10) && v.fitRules.length > 0)).toBe(true);
  });

  it('marks a character whose scan has not started', () => {
    const [outsider] = scanCharacters([{ slug: 'outsider', name: 'Outsider' }]);
    expect(outsider.inactive).toMatch(/voice lane/);
  });
});

describe('the categories with an example from the current picks', () => {
  const pick = (over: Partial<Parameters<typeof tierExamples>[0][number]> = {}) => ({
    tier: null, gallery: false, outlier_x: 150, posted_at: ago(2), views: 3_000_000, total_score: 70, hook: 'a hook', creator_handle: '@c', ...over,
  });

  it('counts each category and names the best-scored pick of it', () => {
    const ex = tierExamples(
      [
        pick({ hook: 'low', total_score: 60 }),
        pick({ hook: 'high', total_score: 91 }),
        pick({ tier: 'iconic', hook: 'famous', total_score: 70 }),
        pick({ gallery: true, hook: null, creator_handle: '@genjutsu', total_score: 66 }),
        pick({ outlier_x: 8, views: 20_000, posted_at: ago(1), hook: 'early', total_score: 75 }),
      ],
      NOW,
    );
    expect(ex.map((e) => [e.tier, e.count, e.example])).toEqual([
      ['iconic', 1, '“famous”'],
      ['viral_now', 2, '“high”'],
      ['rising', 1, '“early”'],
      ['gallery', 1, '@genjutsu'],
    ]);
    expect(ex.map((e) => e.label)).toEqual(TIERS.map((t) => TIER_LABELS[t]));
  });

  it('shows an empty category as zero with no example', () => {
    expect(tierExamples([], NOW).every((e) => e.count === 0 && e.example === null)).toBe(true);
  });
});

describe('the budget', () => {
  it('prices one search each weekday against the plan, with no watches, and the floor that skips a search', () => {
    const b = budgetView(40).vidiq;
    expect([b.perSearch, b.perWatch, b.watchesPerWeek, b.plan, b.used]).toEqual([5, 10, 0, 150, 40]);
    expect(b.pct).toBeCloseTo(26.67, 1);
    expect(b.weekly).toBe(25);
    expect(b.monthlyNeed).toBe(108);
    expect(b.weeklyLine).toBe('5 searches a week, one each weekday (25 credits), about 108 a month; no watches: the free check of an approved clip replaces them');
    expect(b.overPlan).toBe(false);
    expect(SCAN_BUDGET.vidiq_monthly_credits).toBe(150);
    expect([b.floor, b.floorLine]).toEqual([5, 'Below 5 credits the day’s search is skipped (the run says so, with the refill date)']);
    expect(budgetView(999).vidiq.pct).toBe(100);
  });

  it('gives the Higgsfield estimate of each mode from the shared cost model', () => {
    const h = budgetView(0).higgsfield;
    expect(h.map((x) => [x.label, x.credits])).toEqual([['Drop-in, 8 s window', 91], ['Drop-in with an AI beat', 121], ['Recreate', CREDITS.recreate]]);
  });
});

describe('the last scan', () => {
  const run = (over: Partial<RunRow> = {}): RunRow => ({
    id: 'r1', kind: 'daily', started_at: '2026-10-04T07:00:00Z', finished_at: '2026-10-04T07:40:00Z', status: 'ok', summary: null,
    details: { scan: { queries: ['biscuit #2 concept'], outliers: 9, picks_added: 4, auto_approved: 1, held: 1, skipped: 2, vidiq_credits: 15 } }, ...over,
  });

  it('says what it found and filed', () => {
    const v = lastScanView(scannerStatus([run()], NOW).last)!;
    expect(v.when).toBe('Sun 4 Oct 08:40');
    expect(v.line).toBe('9 outliers found, 4 picks filed (1 auto-approved, 1 held, 2 skipped)');
    expect(v.queries).toEqual(['biscuit #2 concept']);
    expect(v.credits).toBe(15);
  });

  it('uses the singular and is null before the first scan', () => {
    const one = run({ details: { scan: { queries: [], outliers: 1, picks_added: 1, auto_approved: 0, held: 0, skipped: 0, vidiq_credits: 5 } } });
    expect(lastScanView(scannerStatus([one], NOW).last)!.line).toBe('1 outlier found, 1 pick filed (0 auto-approved, 0 held, 0 skipped)');
    expect(lastScanView(scannerStatus([], NOW).last)).toBeNull();
  });
});
