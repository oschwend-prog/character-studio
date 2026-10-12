import { createElement } from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, it } from 'vitest';

import { MakeToggle } from './ClipCard';

// Task 14 item 2 (Task 11 ruling, supersedes fix-round finding 10): the Make toggle's accessible name is its visible text.
describe('MakeToggle', () => {
  const html = (ticked: boolean) => renderToStaticMarkup(createElement(MakeToggle, { ticked, onToggle: () => {} }));

  it('has no stable aria-label and no aria-pressed: the changing visible text is the name', () => {
    for (const ticked of [false, true]) {
      const out = html(ticked);
      expect(out).not.toContain('aria-label');
      expect(out).not.toContain('aria-pressed');
    }
  });

  it('shows "Make this" and then "In your list", the mark hidden from a screen reader', () => {
    expect(html(false)).toContain('<span class="cc-mark" aria-hidden="true">＋</span> Make this');
    expect(html(true)).toContain('<span class="cc-mark" aria-hidden="true">✓</span> In your list');
  });
});
