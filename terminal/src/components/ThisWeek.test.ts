// Today's "This week" card (Task 16): the digest as the weekly run wrote it, the proposal link, the empty line, and the score test's label.
import { createElement } from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, it } from 'vitest';
import { DemoBackend } from '../demo/backend';
import { StudioProvider } from '../lib/store';
import { scoreNote } from '../lib/weekly';
import { parseWeekly, type WeeklyDigest } from '../lib/weekly';
import type { RunRow } from '../lib/types';
import { ClipCard, ScoreCaution, showsScoreCaution } from './ClipCard';
import { WeekCard } from './ThisWeek';

const URL_ = 'https://github.com/oschwend-prog/character-studio/compare/build/slice1...weekly/2026-10-12?expand=1';

const week = (over: Record<string, unknown> = {}, status = 'ok'): WeeklyDigest =>
  parseWeekly({
    id: 'r', kind: 'weekly', started_at: '2026-10-19T06:15:00Z', finished_at: '2026-10-19T06:16:00Z', status, summary: '',
    details: {
      week: '2026-10-12',
      digest: {
        header: ['Credits 91 of 6,000 this month', 'Warnings: none · Proposals waiting: none'],
        characters: [
          {
            slug: 'franz', name: 'Franz', bar: 'not yet (10 of 20 posts, day 13 of 28)', title: 'Franz · week of 12 Oct · bar: not yet (10 of 20 posts, day 13 of 28)',
            lines: ['1 Result    5 posts', '2 Audience  followers: none yet', '3 Hook      skip rate: none yet', '4 Tests     score test 14 of 20, his 5 (not a verdict)', '5 Next      too few to call · needs you: nothing'],
          },
          { slug: 'lenny', name: 'Lenny Gold', bar: 'not yet (0 of 20 posts, day 0 of 28)', title: 'Lenny Gold', lines: ['no posts yet'] },
        ],
      },
      proposal_url: null,
      ...over,
    },
  } as RunRow)!;

const html = (w: WeeklyDigest | null, now = new Date('2026-10-19T08:00:00Z')) => renderToStaticMarkup(createElement(WeekCard, { week: w, now }));

describe('WeekCard', () => {
  it('shows the week, the two header lines, each character with his bar and his five labelled lines', () => {
    const out = html(week());
    expect(out).toContain('This week');
    expect(out).toContain('week of 12 Oct');
    expect(out).toContain('Credits 91 of 6,000 this month');
    expect(out).toContain('Warnings: none · Proposals waiting: none');
    expect(out).toContain('bar: not yet (10 of 20 posts, day 13 of 28)');
    for (const label of ['Result', 'Audience', 'Hook', 'Tests', 'Next']) expect(out).toContain(`<dt class="label">${label}</dt>`);
    expect(out).toContain('5 posts');
  });

  it('keeps "not a verdict" visible in the Tests line', () => {
    expect(html(week())).toContain('score test 14 of 20, his 5 (not a verdict)');
  });

  it('a character with no posts is one muted line, no empty list', () => {
    const out = html(week());
    expect(out).toContain('no posts yet');
    expect(out.match(/<dl /g)).toHaveLength(1); // only Franz has lines
  });

  it('links the proposal only when there is one, to GitHub in a new tab', () => {
    expect(html(week())).not.toContain('Proposal waiting');
    const out = html(week({ proposal_url: URL_ }));
    expect(out).toContain('Proposal waiting');
    expect(out).toContain(`href="${URL_.replace(/&/g, '&amp;')}"`);
    expect(out).toContain('target="_blank"');
    expect(out).toContain('rel="noopener noreferrer"');
    expect(out).toContain('opens GitHub in a new tab');
  });

  it('before the first review it is one muted line', () => {
    const out = html(null, new Date('2026-10-14T10:00:00Z'));
    expect(out).toContain('The first weekly review runs on Monday 19 October.');
    expect(out).not.toContain('class="panel');
  });

  it('once Monday 19 October is over without a review, it sends him to the job instead', () => {
    const out = html(null, new Date('2026-10-20T10:00:00Z'));
    expect(out).toContain('No weekly review yet: check the studio-weekly job on GitHub.');
    expect(out).not.toContain('The first weekly review runs on Monday 19 October.');
  });

  it('a clean review shows no problem line', () => {
    const out = html(week());
    expect(out).not.toContain('week-problem');
  });

  it('a review that ended in error shows its status and its notes above the lines', () => {
    const out = html(week({ notes: ['score test failed: RuntimeError: no way', 'digest of reginald failed: RuntimeError: boom'] }, 'error'));
    expect(out).toContain('week-problem');
    expect(out).toContain('Review status: error');
    expect(out).toContain('score test failed: RuntimeError: no way');
    expect(out).toContain('digest of reginald failed: RuntimeError: boom');
    expect(out.indexOf('week-problem')).toBeLessThan(out.indexOf('week-char'));
    expect(out).toContain('<dt class="label">Result</dt>'); // the digest is still there
  });

  it('shows the status of any run that is not ok, even with no notes', () => {
    const out = html(week({}, 'running'));
    expect(out).toContain('Review status: running');
  });
});

describe('the score test label beside a clip score', () => {
  const caution = (n: Parameters<typeof scoreNote>[0]) => renderToStaticMarkup(createElement(ScoreCaution, { note: scoreNote(n), className: 'x' }));

  it('unproven is a small label with its reason in the title and for a screen reader', () => {
    const out = caution({ label: 'unproven', n: 14, needed: 20, look: null });
    expect(out).toContain('>unproven<');
    expect(out).toContain('title="Score test: 14 of 20 posts so far. Not a verdict."');
    expect(out).toContain('<span class="sr-only">. Score test: 14 of 20 posts so far. Not a verdict.</span>');
  });

  it('validated shows nothing at all', () => {
    expect(caution({ label: 'validated', n: 20, needed: 20, look: 20 })).toBe('');
  });

  it('failed says the score does not predict views yet; uninformative is unproven', () => {
    expect(caution({ label: 'failed', n: 20, needed: 20, look: 20 })).toContain('unproven: does not predict views yet');
    expect(caution({ label: 'uninformative', n: 20, needed: 40, look: 20 })).toContain('>unproven<');
  });
});

describe('ClipCard with the score test', () => {
  const card = (score: number | null | undefined, over: Record<string, unknown> = {}) =>
    renderToStaticMarkup(
      createElement(StudioProvider, {
        backend: new DemoBackend(),
        children: createElement(ClipCard, {
          id: 'f-1', title: 'A clip', picture: { sources: [], thumb: { thumbnail_url: null, platform: 'tiktok', creator_handle: null } as never },
          playable: { kind: 'none' }, score, ...over,
        }),
      }),
    );

  it('before any weekly review the check score says unproven', () => {
    const out = card(72, { checkScore: true });
    expect(out).toContain('cc-score-note');
    expect(out).toContain('>unproven<');
  });

  it('a clip with no score, or a card that shows no score, gets no label', () => {
    expect(card(null, { checkScore: true })).not.toContain('cc-score-note');
    expect(card(undefined, { checkScore: true })).not.toContain('cc-score-note');
  });

  it('a Hits card ("How hot") is not the check score: no label, whatever the test says', () => {
    expect(card(72, { scoreLabel: 'How hot' })).not.toContain('cc-score-note');
    expect(card(72)).not.toContain('cc-score-note'); // a score nobody said is the check's gets no caution either
  });

  it('the card and its player sheet share one rule: the check score only, and only when there is a score', () => {
    expect(showsScoreCaution(72, true)).toBe(true);
    expect(showsScoreCaution(0, true)).toBe(true); // a score of 0 is a score
    expect(showsScoreCaution(72, false)).toBe(false);
    expect(showsScoreCaution(72, undefined)).toBe(false); // the player sheet of a hit
    expect(showsScoreCaution(null, true)).toBe(false);
    expect(showsScoreCaution(undefined, true)).toBe(false);
  });
});
