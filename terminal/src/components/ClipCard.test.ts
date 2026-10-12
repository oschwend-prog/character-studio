import { createElement } from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, it } from 'vitest';

import { DemoBackend } from '../demo/backend';
import { StudioProvider } from '../lib/store';
import { ClipCard, MakeToggle } from './ClipCard';

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

// Task 15 fix 1 (minor 3, 7): the Explore card says why it is there and shows no rank (its real rank is lower).
describe('ClipCard, an Explore clip', () => {
  const card = (props: { rank?: number | null; explore?: boolean }) =>
    renderToStaticMarkup(
      createElement(StudioProvider, {
        backend: new DemoBackend(),
        children: createElement(ClipCard, {
          id: 'f-1', title: 'A clip', picture: { sources: [], thumb: { thumbnail_url: null, platform: 'tiktok', creator_handle: null } as never },
          playable: { kind: 'none' }, score: 41, ...props,
        }),
      }),
    );

  it('shows the Explore label and its reason, and no rank', () => {
    const out = card({ rank: null, explore: true });
    expect(out).toContain('Explore');
    expect(out).toContain('below his median score');
    expect(out).not.toContain('cc-rank');
  });

  it('a ranked card shows its rank and no Explore label', () => {
    const out = card({ rank: 2 });
    expect(out).toContain('#2');
    expect(out).not.toContain('below his median score');
  });
});
