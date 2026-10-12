// The weekly review on Today (learning plan 6.1, Task 16): reading the latest `weekly` run, and the score test's label on a clip's score.
import { describe, expect, it } from 'vitest';
import { FIRST_WEEKLY_NOTE, parseWeekly, rankOrderFor, scoreNote, scoreTestOf, splitLine, weekLabel } from './weekly';
import type { RunRow } from './types';

const digest = {
  header: ['Credits 91 of 6,000 this month (2 %, 0 still reserved; last month 0) · cost per 1K views: none yet (no views read this month)', 'Warnings: none · Proposals waiting: none'],
  characters: [
    {
      slug: 'franz', name: 'Franz', bar: 'not yet (10 of 20 posts, day 13 of 28)', bar_status: 'not_yet',
      title: 'Franz · week of 12 Oct · bar: not yet (10 of 20 posts, day 13 of 28)',
      lines: ['1 Result    5 posts (last week 5)', '2 Audience  followers: none yet', '3 Hook      skip rate: none yet', '4 Tests     score test 14 of 20, his 5 (not a verdict)', '5 Next      too few to call · needs you: nothing'],
    },
    { slug: 'lenny', name: 'Lenny Gold', bar: 'not yet (0 of 20 posts, day 0 of 28)', bar_status: 'not_yet', title: 'Lenny Gold · week of 12 Oct · bar: not yet (0 of 20 posts, day 0 of 28)', lines: ['no posts yet'] },
  ],
};

const run = (details: RunRow['details'], over: Partial<RunRow> = {}): RunRow => ({
  id: 'r1', kind: 'weekly', started_at: '2026-10-19T06:15:00Z', finished_at: '2026-10-19T06:16:00Z', status: 'ok', summary: 'x', details, ...over,
});

describe('parseWeekly', () => {
  it('reads the week, the two header lines and every character with his lines', () => {
    const w = parseWeekly(run({ week: '2026-10-12', digest, proposal_url: null }));
    expect(w).not.toBeNull();
    expect(w!.week).toBe('2026-10-12');
    expect(w!.label).toBe('week of 12 Oct');
    expect(w!.header).toHaveLength(2);
    expect(w!.characters.map((c) => c.slug)).toEqual(['franz', 'lenny']);
    expect(w!.characters[0].lines).toHaveLength(5);
    expect(w!.characters[0].title).toContain('Franz · week of 12 Oct');
    expect(w!.characters[0].bar).toBe('not yet (10 of 20 posts, day 13 of 28)');
    expect(w!.characters[1].lines).toEqual(['no posts yet']);
    expect(w!.proposalUrl).toBeNull();
  });

  it('is null for no run, a run without a digest and a digest that is not the shape', () => {
    expect(parseWeekly(null)).toBeNull();
    expect(parseWeekly(undefined)).toBeNull();
    expect(parseWeekly(run(null))).toBeNull();
    expect(parseWeekly(run({}))).toBeNull();
    expect(parseWeekly(run({ week: '2026-10-12', digest: 'nope' }))).toBeNull();
    expect(parseWeekly(run({ week: 'last week', digest }))).toBeNull();
  });

  it('keeps only well-formed header lines and characters', () => {
    const w = parseWeekly(run({
      week: '2026-10-12',
      digest: { header: ['one', 7, null, 'two'], characters: [{ slug: 'franz', name: 'Franz', lines: ['a', 3, 'b'] }, 'junk', { name: 'no slug', lines: [] }, { slug: 'x', lines: 'no' }] },
    }));
    expect(w!.header).toEqual(['one', 'two']);
    expect(w!.characters).toHaveLength(1);
    expect(w!.characters[0]).toMatchObject({ slug: 'franz', name: 'Franz', lines: ['a', 'b'], title: 'Franz', bar: '' });
  });

  it('links the proposal only when it is an https address', () => {
    const url = 'https://github.com/oschwend-prog/character-studio/compare/build/slice1...weekly/2026-10-12?expand=1';
    expect(parseWeekly(run({ week: '2026-10-12', digest, proposal_url: url }))!.proposalUrl).toBe(url);
    for (const bad of ['javascript:alert(1)', 'http://github.com/x', '', 5, null]) {
      expect(parseWeekly(run({ week: '2026-10-12', digest, proposal_url: bad }))!.proposalUrl).toBeNull();
    }
  });

  it('shows a run that ended in error too: the digest is there, with the notes', () => {
    const w = parseWeekly(run({ week: '2026-10-12', digest }, { status: 'error' }));
    expect(w).not.toBeNull();
    expect(w!.status).toBe('error');
  });
});

describe('splitLine', () => {
  it('separates the label from the text of a labelled line', () => {
    expect(splitLine('1 Result    5 posts (last week 5)')).toEqual({ label: 'Result', text: '5 posts (last week 5)' });
    expect(splitLine('2 Audience  followers: none yet')).toEqual({ label: 'Audience', text: 'followers: none yet' });
    expect(splitLine('5 Next      too few to call · needs you: nothing')).toEqual({ label: 'Next', text: 'too few to call · needs you: nothing' });
  });
  it('leaves any other line whole, with no label', () => {
    expect(splitLine('no posts yet')).toEqual({ label: null, text: 'no posts yet' });
    expect(splitLine('')).toEqual({ label: null, text: '' });
    expect(splitLine('6 Other  x')).toEqual({ label: null, text: '6 Other  x' });
  });
});

describe('weekLabel', () => {
  it('says the week of the Monday, in the owner\'s words', () => {
    expect(weekLabel('2026-10-12')).toBe('week of 12 Oct');
    expect(weekLabel('2026-11-02')).toBe('week of 2 Nov');
    expect(weekLabel('2027-01-04')).toBe('week of 4 Jan');
  });
  it('keeps a text it cannot read', () => {
    expect(weekLabel('soon')).toBe('soon');
  });
});

it('says when the first review is due', () => {
  expect(FIRST_WEEKLY_NOTE).toBe('The first weekly review runs on Monday 19 October.');
});

describe('the score test label (test A, plan 3.2)', () => {
  const test = (st: unknown) => scoreTestOf(run({ week: '2026-10-12', digest, score_test: st }));

  it('no weekly run yet is unproven', () => {
    expect(scoreTestOf(null)).toEqual({ label: 'unproven', n: null, needed: null, look: null });
    expect(scoreTestOf(undefined).label).toBe('unproven');
    expect(scoreTestOf(run(null)).label).toBe('unproven');
    expect(scoreTestOf(run({ week: '2026-10-12', digest })).label).toBe('unproven'); // a run from before the score test existed
  });

  it('reads the label, n, needed and look of the latest run', () => {
    expect(test({ label: 'validated', n: 22, needed: 20, look: 20 })).toEqual({ label: 'validated', n: 22, needed: 20, look: 20 });
    expect(test({ label: 'failed', n: 40, needed: 40, look: 40 }).label).toBe('failed');
    expect(test({ label: 'uninformative', n: 20, needed: 40, look: 20 }).label).toBe('uninformative');
  });

  it('treats anything it does not know as unproven, never as validated', () => {
    expect(test({ label: 'great' }).label).toBe('unproven');
    expect(test({ label: 7 }).label).toBe('unproven');
    expect(test('validated').label).toBe('unproven');
    expect(test({ label: 'unproven', n: 'many', needed: -1 })).toEqual({ label: 'unproven', n: null, needed: null, look: null });
  });

  it('unproven: a small muted "unproven" whose title gives n of the posts needed and says it is no verdict', () => {
    expect(scoreNote({ label: 'unproven', n: 14, needed: 20, look: null })).toEqual({
      text: 'unproven', title: 'Score test: 14 of 20 posts so far. Not a verdict.',
    });
    expect(scoreNote({ label: 'unproven', n: null, needed: null, look: null })!.title).toBe('Score test: no posts counted yet. Not a verdict.');
  });

  it('validated: no label at all', () => {
    expect(scoreNote({ label: 'validated', n: 20, needed: 20, look: 20 })).toBeNull();
  });

  it('failed: says it does not predict views yet', () => {
    const note = scoreNote({ label: 'failed', n: 20, needed: 20, look: 20 })!;
    expect(note.text).toBe('unproven: does not predict views yet');
    expect(note.title).toContain('does not predict views');
  });

  it('uninformative: unproven, with the reason', () => {
    const note = scoreNote({ label: 'uninformative', n: 20, needed: 40, look: 20 })!;
    expect(note.text).toBe('unproven');
    expect(note.title).toContain('Not a verdict');
  });

  it('only a failed test changes how Make these is ordered', () => {
    const info = (label: 'unproven' | 'validated' | 'failed' | 'uninformative') => ({ label, n: 20, needed: 20, look: 20 });
    expect(rankOrderFor(info('failed'))).toBe('freshness');
    for (const label of ['unproven', 'validated', 'uninformative'] as const) expect(rankOrderFor(info(label))).toBe('score');
  });
});
