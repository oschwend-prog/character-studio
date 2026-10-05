import { describe, expect, it } from 'vitest';
import { AI_DISCLOSURE, captionLength, cleanTags, composeContent, copyText, postText } from './captions';
import parity from './parity-cases.json';

interface CaptionCase {
  caption: string;
  repeat?: number;
  hashtags: string[];
  expect?: string;
  expect_length?: number;
  error?: string;
}

describe('composeContent mirrors studio.captions.compose_content', () => {
  for (const c of (parity as unknown as { captions: CaptionCase[] }).captions) {
    it(`${c.error ?? c.expect?.slice(0, 40) ?? `length ${c.expect_length}`}`, () => {
      const caption = c.caption.repeat(c.repeat ?? 1);
      if (c.error) {
        expect(() => composeContent(caption, c.hashtags)).toThrow(c.error);
        return;
      }
      const out = composeContent(caption, c.hashtags);
      if (c.expect !== undefined) expect(out).toBe(c.expect);
      if (c.expect_length !== undefined) expect(captionLength(out)).toBe(c.expect_length);
      expect(out).toContain(AI_DISCLOSURE);
    });
  }

  it('cleans the tags like the studio', () => {
    expect(cleanTags([' #a ', 'A', '##b', '', '#', 'c'])).toEqual(['#a', '#b', '#c']);
  });

  it('gives the screen the text or the reason, never a crash', () => {
    expect(postText('lead dancer. obviously. 💙', ['#oddeyes'])).toEqual({ text: `lead dancer. obviously. 💙\n\n${AI_DISCLOSURE}\n\n#oddeyes`, error: null });
    expect(postText(null, null)).toEqual({ text: AI_DISCLOSURE, error: null });
    const bad = postText('x', ['#fyp']);
    expect(bad.text).toBeNull();
    expect(bad.error).toMatch(/#fyp is refused/);
  });
});

describe('the Copy button', () => {
  it('uses the clipboard when it takes the text', async () => {
    const got: string[] = [];
    expect(await copyText('hello', { writeText: async (t: string) => void got.push(t) })).toBe('copied');
    expect(got).toEqual(['hello']);
  });

  it('falls back to "select and copy" when the clipboard is missing or refuses', async () => {
    expect(await copyText('hello', undefined)).toBe('select');
    expect(await copyText('hello', null)).toBe('select');
    expect(await copyText('hello', { writeText: () => Promise.reject(new DOMException('denied', 'NotAllowedError')) })).toBe('select');
    expect(await copyText('hello', { writeText: () => { throw new Error('sync failure'); } })).toBe('select');
  });
});
