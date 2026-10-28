// Today's "Comments to post today" card (owner 2026-10-28): per character the account, an Open post link in a new tab, the comment and a
// Copy button; nothing at all when there are no drafts. The demo backend's fixture feeds the same card the app shows in demo mode.
import { createElement } from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, it, vi } from 'vitest';
import { DemoBackend } from '../demo/backend';
import { draftsForDay, groupDrafts } from '../lib/comments';
import { londonDayKey } from '../lib/format';
import { CommentsCard, copyDraft } from './CommentDrafts';

const franz = { character: 'franz', handle: '@godivathedachshund', postUrl: 'https://www.instagram.com/reel/DeFNvlUJ_WE/', comment: 'He walks like he pays rent on the whole floor.' };
const reginald = { character: 'reginald', handle: '@jamiemiller', postUrl: 'https://www.instagram.com/reel/DeMny/', comment: 'One notes the technique & the <lighting>.' };

const html = (drafts = [franz, reginald]) =>
  renderToStaticMarkup(createElement(CommentsCard, { groups: groupDrafts(drafts, [{ slug: 'franz', name: 'Franz' }, { slug: 'reginald', name: 'Reginald' }]) }));

describe('CommentsCard', () => {
  it('is a section called "Comments to post today" with the number of comments', () => {
    const out = html();
    expect(out).toContain('Comments to post today');
    expect(out).toMatch(/<div class="aside"><span class="num">2<\/span><\/div>/);
    expect(out).toContain('post it yourself from his account');
  });

  it('lists each character’s comments under his name, in the owner’s order', () => {
    const out = html([reginald, franz]);
    expect(out.indexOf('Franz')).toBeGreaterThan(-1);
    expect(out.indexOf('Franz')).toBeLessThan(out.indexOf('Reginald'));
    expect(out).toContain('aria-label="Franz’s comments to post"');
    expect(out.match(/<li class="pipe-row"/g)).toHaveLength(2);
  });

  it('shows the @handle, the comment, an Open post link that opens a new tab, and a Copy button for each', () => {
    const out = html([franz]);
    expect(out).toContain('@godivathedachshund');
    expect(out).toContain('He walks like he pays rent on the whole floor.');
    expect(out).toContain('href="https://www.instagram.com/reel/DeFNvlUJ_WE/"');
    expect(out).toContain('target="_blank"');
    expect(out).toContain('rel="noopener noreferrer"');
    expect(out).toContain('Open post');
    expect(out).toMatch(/<button type="button" class="btn line"[^>]*aria-label="Copy the comment for @godivathedachshund"[^>]*>[\s\S]*Copy<\/button>/);
    expect(out).not.toContain('Copied'); // the short "Copied" only shows after a copy
  });

  it('escapes the comment text (it is data)', () => {
    const out = html([reginald]);
    expect(out).toContain('One notes the technique &amp; the &lt;lighting&gt;.');
    expect(out).not.toContain('<lighting>');
  });

  it('reuses the neighbouring card’s own parts and brings no new style', () => {
    const out = html();
    for (const cls of ['class="section"', 'class="panel rows"', 'class="panel-pad"', 'class="pipe-list"', 'class="pipe-meta"', 'class="pipe-hook"', 'class="link"', 'btn line']) {
      expect(out).toContain(cls);
    }
    expect(out).toContain('<ul class="pipe-list"');
  });

  it('renders nothing when there are no drafts', () => {
    expect(renderToStaticMarkup(createElement(CommentsCard, { groups: [] }))).toBe('');
    expect(renderToStaticMarkup(createElement(CommentsCard, { groups: [{ slug: 'franz', name: 'Franz', drafts: [] }] }))).toBe('');
  });
});

describe('Copy', () => {
  it('writes the comment to the clipboard', async () => {
    const writeText = vi.fn(async () => undefined);
    expect(await copyDraft(franz, { writeText })).toBe('copied');
    expect(writeText).toHaveBeenCalledExactlyOnceWith('He walks like he pays rent on the whole floor.');
  });

  it('asks the page to select the text when the clipboard is missing or refuses', async () => {
    expect(await copyDraft(franz, undefined)).toBe('select');
    expect(await copyDraft(franz, { writeText: async () => Promise.reject(new Error('denied')) })).toBe('select');
  });
});

describe('the demo fixture', () => {
  it('has drafts for today’s London day for each live character, and only for them', async () => {
    const data = await new DemoBackend().load();
    const today = draftsForDay(data.commentDrafts, londonDayKey(data.loadedAt));
    const groups = groupDrafts(today, data.characters);
    expect(groups.map((g) => g.slug)).toEqual(['franz', 'reginald', 'lenny']);
    expect(groups.every((g) => g.drafts.length >= 2)).toBe(true);
    expect(today.every((d) => d.comment.length <= 200 && !/https?:|#/.test(d.comment))).toBe(true);
    expect(renderToStaticMarkup(createElement(CommentsCard, { groups }))).toContain('Comments to post today');
  });
});
