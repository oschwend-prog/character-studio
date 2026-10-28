// "Comments to post today" (owner 2026-10-28): the stored drafts (runs of kind comment_drafts) as the card reads them.
import { describe, expect, it } from 'vitest';
import { draftsForDay, groupDrafts, isPostUrl, parseCommentDays } from './comments';

const draft = (over: Record<string, unknown> = {}) => ({
  character: 'franz',
  handle: '@godivathedachshund',
  post_url: 'https://www.instagram.com/reel/DeFNvlUJ_WE/',
  comment: 'He walks like he pays rent on the whole floor.',
  ...over,
});
const row = (day: string, drafts: unknown) => ({ details: { day, drafts } });

describe('parseCommentDays', () => {
  it('reads the days oldest first, with the drafts as the run stored them', () => {
    const got = parseCommentDays([row('2026-10-28', [draft()]), row('2026-10-27', [draft({ handle: 'plain' })])]);
    expect(got.map((d) => d.day)).toEqual(['2026-10-27', '2026-10-28']);
    expect(got[1].drafts).toEqual([
      { character: 'franz', handle: '@godivathedachshund', postUrl: 'https://www.instagram.com/reel/DeFNvlUJ_WE/', comment: 'He walks like he pays rent on the whole floor.' },
    ]);
    expect(got[0].drafts[0].handle).toBe('@plain'); // always with its @
  });

  it('leaves out a draft with a missing field, and a run with no usable day or drafts', () => {
    const got = parseCommentDays([
      row('2026-10-28', [draft(), draft({ comment: '  ' }), draft({ handle: undefined }), draft({ character: 3 }), 'text', null, draft({ post_url: '' })]),
      row('yesterday', [draft()]),
      row('2026-10-26', []),
      row('2026-10-25', 'not a list'),
      { details: null },
      null,
      undefined,
      {},
    ]);
    expect(got.map((d) => d.day)).toEqual(['2026-10-28']);
    expect(got[0].drafts).toHaveLength(1);
  });

  it('only keeps a post link that is an https Instagram link (a stored value is data, never a script or another site)', () => {
    const bad = ['javascript:alert(1)', 'http://www.instagram.com/p/x/', 'https://evil.example/p/x', 'https://instagram.com.evil.example/p/x', 'not a url'];
    const got = parseCommentDays([row('2026-10-28', [...bad.map((u, i) => draft({ post_url: u, handle: `@h${i}` })), draft({ handle: '@ok', post_url: 'https://instagram.com/p/abc/' })])]);
    expect(got[0].drafts.map((d) => d.handle)).toEqual(['@ok']);
    expect(isPostUrl('https://www.instagram.com/reel/x/')).toBe(true);
    expect(isPostUrl('https://notinstagram.com/reel/x/')).toBe(false);
  });

  it('joins two rows of one day and lists an account once per character, the later row winning', () => {
    const got = parseCommentDays([
      row('2026-10-28', [draft({ comment: 'first' }), draft({ handle: '@other', comment: 'kept' })]),
      row('2026-10-28', [draft({ handle: '@GodivaTheDachshund', comment: 'second' }), draft({ character: 'reginald', comment: 'his own' })]),
    ]);
    expect(got).toHaveLength(1);
    expect(got[0].drafts.map((d) => `${d.character} ${d.handle} ${d.comment}`)).toEqual([
      'franz @GodivaTheDachshund second',
      'franz @other kept',
      'reginald @godivathedachshund his own',
    ]);
  });

  it('is empty for nothing', () => {
    expect(parseCommentDays([])).toEqual([]);
  });
});

describe('draftsForDay', () => {
  const days = parseCommentDays([row('2026-10-27', [draft({ comment: 'yesterday' })]), row('2026-10-28', [draft({ comment: 'today' })])]);

  it('picks the London day asked for, and nothing from another day', () => {
    expect(draftsForDay(days, '2026-10-28').map((d) => d.comment)).toEqual(['today']);
    expect(draftsForDay(days, '2026-10-29')).toEqual([]);
  });

  it('is empty before the first row', () => {
    expect(draftsForDay(undefined, '2026-10-28')).toEqual([]);
    expect(draftsForDay([], '2026-10-28')).toEqual([]);
  });
});

describe('groupDrafts', () => {
  const drafts = parseCommentDays([
    row('2026-10-28', [
      draft({ character: 'lenny', handle: '@l1' }),
      draft({ character: 'franz', handle: '@f1' }),
      draft({ character: 'lenny', handle: '@l2' }),
      draft({ character: 'reginald', handle: '@r1' }),
      draft({ character: 'borat-type', handle: '@b1' }),
      draft({ character: 'biscuit', handle: '@old' }),
    ]),
  ])[0].drafts;

  it('groups by character in the owner’s order (Franz, Reginald, Lenny, any other, a paused one last), each group in the order written', () => {
    const groups = groupDrafts(drafts, [
      { slug: 'franz', name: 'Franz', status: 'live' },
      { slug: 'reginald', name: 'Reginald', status: 'live' },
      { slug: 'lenny', name: 'Lenny Gold', status: 'live' },
      { slug: 'biscuit', name: 'Biscuit', status: 'paused' },
    ]);
    expect(groups.map((g) => g.slug)).toEqual(['franz', 'reginald', 'lenny', 'borat-type', 'biscuit']);
    expect(groups.map((g) => g.name)).toEqual(['Franz', 'Reginald', 'Lenny Gold', 'Borat Type', 'Biscuit']);
    expect(groups[2].drafts.map((d) => d.handle)).toEqual(['@l1', '@l2']);
  });

  it('works before the characters have loaded', () => {
    expect(groupDrafts(drafts.slice(0, 2)).map((g) => g.name)).toEqual(['Franz', 'Lenny Gold']);
    expect(groupDrafts([])).toEqual([]);
  });
});
