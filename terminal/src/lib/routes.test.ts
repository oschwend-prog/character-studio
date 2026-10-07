// The five sections (Today, Clips, Videos, Characters, More) and the old addresses that must keep working
// (terminal v2 spec part B; owner 2026-10-07). Pure helpers only: vitest runs in node, there is no DOM.
import { describe, expect, it } from 'vitest';
import { HOME, ROUTES, href, parseHash, upgradeHash } from './hooks';
import { CHARACTERS_VIEWS, MORE_VIEWS, TABS, charactersView, moreView } from './tabs';

describe('the five sections', () => {
  it('opens on Today and has one route per section, plus the artist page without a tab', () => {
    expect(HOME).toBe('today');
    expect(ROUTES).toEqual(['today', 'clips', 'videos', 'characters', 'more', 'artist']);
  });

  it('lists the tabs in the order of the work, with no "later" mark on any of them', () => {
    expect(TABS.map((t) => t.route)).toEqual(['today', 'clips', 'videos', 'characters', 'more']);
    expect(TABS.map((t) => t.label)).toEqual(['Today', 'Clips', 'Videos', 'Characters', 'More']);
    expect(TABS.some((t) => 'later' in t)).toBe(false);
    // every route except the artist page has its tab
    expect(new Set(TABS.map((t) => t.route))).toEqual(new Set(ROUTES.filter((r) => r !== 'artist')));
  });

  it('reads the new addresses with their one parameter and their query', () => {
    expect(parseHash('#/clips')).toEqual({ route: 'clips', param: null, query: '' });
    expect(parseHash('#/videos/abc-123')).toEqual({ route: 'videos', param: 'abc-123', query: '' });
    expect(parseHash('#/characters/all?clip=abc-123')).toEqual({ route: 'characters', param: 'all', query: 'clip=abc-123' });
    expect(parseHash('#/more/scan?c=franz')).toEqual({ route: 'more', param: 'scan', query: 'c=franz' });
    expect(parseHash('#/more/budget')).toEqual({ route: 'more', param: 'budget', query: '' });
    expect(parseHash('#/artist/franz')).toEqual({ route: 'artist', param: 'franz', query: '' });
  });

  it('falls back to Today for an empty or unknown address', () => {
    expect(parseHash('')).toEqual({ route: 'today', param: null, query: '' });
    expect(parseHash('#/')).toEqual({ route: 'today', param: null, query: '' });
    expect(parseHash('#/nonsense')).toEqual({ route: 'today', param: null, query: '' });
    expect(parseHash('#/nonsense?c=x').route).toBe('today');
  });

  it('builds the links: Today is the bare #/, the others carry their parameter and query', () => {
    expect(href('today')).toBe('#/');
    expect(href('clips')).toBe('#/clips');
    expect(href('videos', 'abc')).toBe('#/videos/abc');
    expect(href('characters')).toBe('#/characters');
    expect(href('characters', 'all', { clip: 'abc' })).toBe('#/characters/all?clip=abc');
    expect(href('more', 'scan', { c: 'franz' })).toBe('#/more/scan?c=franz');
    expect(href('more', 'scan', { view: 'list' })).toBe('#/more/scan?view=list');
    expect(href('more', 'budget')).toBe('#/more/budget');
    expect(href('artist', 'lenny')).toBe('#/artist/lenny');
  });
});

describe('old bookmarks land on the right new page (upgradeHash)', () => {
  const ID = '06eb86e9-1c2d-4e5f-8a9b-0c1d2e3f4a5b';
  const legacy: Array<[string, string]> = [
    ['#/works', '#/clips'],
    ['#/queue', '#/videos'],
    [`#/queue/${ID}`, `#/videos/${ID}`],
    ['#/library', '#/characters/all'],
    [`#/library/${ID}`, `#/characters/all?clip=${ID}`],
    ['#/channels', '#/characters'],
    ['#/picks', '#/more/scan'],
    ['#/picks?c=franz', '#/more/scan?c=franz'],
    ['#/picks?view=list', '#/more/scan?view=list'],
    ['#/budget', '#/more/budget'],
    ['#/today', '#/'],
  ];

  it.each(legacy)('%s -> %s', (old, now) => {
    expect(upgradeHash(old)).toBe(now);
  });

  it('keeps the query a deep link carried', () => {
    expect(upgradeHash('#/picks?c=franz&view=list')).toBe('#/more/scan?c=franz&view=list');
    expect(upgradeHash(`#/queue/${ID}?c=reginald`)).toBe(`#/videos/${ID}?c=reginald`);
    expect(upgradeHash('#/library?c=lenny')).toBe('#/characters/all?c=lenny');
    expect(upgradeHash(`#/library/${ID}?c=lenny`)).toBe(`#/characters/all?clip=${ID}&c=lenny`);
  });

  it('takes the hash without the slash too, as parseHash does', () => {
    expect(upgradeHash('#works')).toBe('#/clips');
    expect(upgradeHash('#picks?c=franz')).toBe('#/more/scan?c=franz');
  });

  it('leaves the new addresses, the artist page and the unknown ones alone (null)', () => {
    for (const h of ['', '#', '#/', '#/clips', '#/videos', `#/videos/${ID}`, '#/characters', '#/characters/all', '#/more', '#/more/scan', '#/more/budget', '#/artist/franz', '#/nonsense']) {
      expect(upgradeHash(h)).toBeNull();
    }
    expect(upgradeHash('#/clips')).toBeNull();
  });

  it('is stable: the address it returns is never upgraded again', () => {
    for (const [, now] of legacy) expect(upgradeHash(now)).toBeNull();
  });

  it('every address it returns parses to a real route, and the old parameter survives', () => {
    expect(parseHash(upgradeHash(`#/queue/${ID}`)!)).toEqual({ route: 'videos', param: ID, query: '' });
    expect(parseHash(upgradeHash(`#/library/${ID}`)!)).toEqual({ route: 'characters', param: 'all', query: `clip=${ID}` });
    expect(parseHash(upgradeHash('#/picks?c=franz')!)).toEqual({ route: 'more', param: 'scan', query: 'c=franz' });
    expect(parseHash(upgradeHash('#/budget')!)).toEqual({ route: 'more', param: 'budget', query: '' });
    expect(parseHash(upgradeHash('#/today')!)).toEqual({ route: 'today', param: null, query: '' });
  });
});

describe('the views inside Characters and More', () => {
  const ID = '06eb86e9-1c2d-4e5f-8a9b-0c1d2e3f4a5b';

  it('More opens on the Scan, and an unknown view is the Scan', () => {
    expect(MORE_VIEWS.map((v) => v.id)).toEqual(['scan', 'budget', 'health']);
    expect(MORE_VIEWS.map((v) => v.label)).toEqual(['Scan', 'Budget', 'Health']);
    expect([moreView(null), moreView(undefined), moreView(''), moreView('scan'), moreView('nonsense')]).toEqual(['scan', 'scan', 'scan', 'scan', 'scan']);
    expect([moreView('budget'), moreView('health')]).toEqual(['budget', 'health']);
  });

  it('Characters shows the cards, and `all` every video', () => {
    expect(CHARACTERS_VIEWS.map((v) => v.label)).toEqual(['Characters', 'All videos']);
    expect([charactersView(null), charactersView('franz'), charactersView('nonsense')]).toEqual(['cards', 'cards', 'cards']);
    expect(charactersView('all')).toBe('all');
  });

  it('every link of the views builds an address that reads back as the same view', () => {
    for (const v of MORE_VIEWS) expect(moreView(parseHash(href('more', v.id)).param)).toBe(v.id);
    expect(charactersView(parseHash(href('characters')).param)).toBe('cards');
    expect(charactersView(parseHash(href('characters', 'all')).param)).toBe('all');
  });

  it('the old bookmarks land on the right view with their parameter', () => {
    const queue = parseHash(upgradeHash(`#/queue/${ID}`)!);
    expect([queue.route, queue.param]).toEqual(['videos', ID]); // Videos reads the clip to show from the parameter
    const library = parseHash(upgradeHash(`#/library/${ID}`)!);
    expect([library.route, charactersView(library.param), new URLSearchParams(library.query).get('clip')]).toEqual(['characters', 'all', ID]);
    const channels = parseHash(upgradeHash('#/channels')!);
    expect([channels.route, charactersView(channels.param)]).toEqual(['characters', 'cards']);
    const picks = parseHash(upgradeHash('#/picks?c=franz&view=list')!);
    expect([picks.route, moreView(picks.param), new URLSearchParams(picks.query).get('c'), new URLSearchParams(picks.query).get('view')]).toEqual(['more', 'scan', 'franz', 'list']);
    const budget = parseHash(upgradeHash('#/budget')!);
    expect([budget.route, moreView(budget.param)]).toEqual(['more', 'budget']);
  });
});
