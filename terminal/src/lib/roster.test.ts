import { describe, expect, it } from 'vitest';
import { ROSTER, activeRoster, characterCards, isPaused, liveryClass, nameOf, orderRoster } from './roster';
import type { Channel, Character } from './types';

describe('the roster (owner 2026-10-06: Franz, Reginald, Lenny Gold; Biscuit retired)', () => {
  it('names the known characters and turns an unknown slug into words', () => {
    expect(ROSTER.map((c) => c.slug)).toEqual(['franz', 'reginald', 'lenny']);
    expect([nameOf('franz'), nameOf('lenny'), nameOf('biscuit')]).toEqual(['Franz', 'Lenny Gold', 'Biscuit']);
    expect(nameOf('borat-type')).toBe('Borat Type'); // the Borat-type, once he has a folder, before his name is seeded
  });

  it('gives a livery only to the slugs styles.css paints; any other gets the neutral plate', () => {
    expect(['franz', 'reginald', 'lenny', 'biscuit'].map(liveryClass)).toEqual(['franz', 'reginald', 'lenny', 'biscuit']);
    expect([liveryClass('borat-type'), liveryClass(null), liveryClass('')]).toEqual(['none', 'none', 'none']);
  });

  it('orders the characters the owner’s way: the roster, then others by slug, a paused one last', () => {
    const view = [
      { slug: 'biscuit', status: 'paused' }, { slug: 'franz', status: 'designing' }, { slug: 'zed', status: 'designing' },
      { slug: 'lenny', status: 'designing' }, { slug: 'borat-type', status: 'designing' }, { slug: 'reginald', status: 'live' },
    ];
    expect(orderRoster(view).map((c) => c.slug)).toEqual(['franz', 'reginald', 'lenny', 'borat-type', 'zed', 'biscuit']);
    expect(view[0].slug).toBe('biscuit'); // the input is left as it was
  });

  it('offers only characters that are not paused for a new video, the roster while nothing has loaded', () => {
    const loaded = [
      { slug: 'biscuit', name: 'Biscuit', status: 'paused' }, { slug: 'lenny', name: 'Lenny Gold', status: 'designing' },
      { slug: 'reginald', name: 'Reginald', status: 'live' },
    ];
    expect(activeRoster(loaded)).toEqual([{ slug: 'reginald', name: 'Reginald' }, { slug: 'lenny', name: 'Lenny Gold' }]);
    expect(activeRoster([])).toEqual([...ROSTER]);
    expect(activeRoster(null)).toEqual([...ROSTER]);
    expect([isPaused({ status: 'paused' }), isPaused({ status: 'live' }), isPaused({})]).toEqual([true, false, false]);
  });
});

describe('the Characters page cards (characterCards)', () => {
  const NOW = Date.parse('2026-10-07T12:00:00Z');
  const ahead = (h: number) => new Date(NOW + h * 3_600_000).toISOString();
  const character = (slug: string, status: string, over: Partial<Character> = {}): Character => ({
    slug, name: nameOf(slug), status, bodies: [], setup: {}, accounts: [], ...over,
  });
  const channel = (slug: string, platform: Channel['platform'], over: Partial<Channel> = {}): Pick<Channel, 'character_slug' | 'platform' | 'connected' | 'next_slot'> => ({
    character_slug: slug, platform, connected: true, next_slot: null, ...over,
  });

  it('comes in the owner’s order, a retired character last, each with his status', () => {
    const cards = characterCards(
      [character('biscuit', 'paused'), character('lenny', 'designing'), character('franz', 'live'), character('reginald', 'live')], [], NOW,
    );
    expect(cards.map((c) => [c.slug, c.name, c.status])).toEqual([
      ['franz', 'Franz', 'live'], ['reginald', 'Reginald', 'live'], ['lenny', 'Lenny Gold', 'designing'], ['biscuit', 'Biscuit', 'paused'],
    ]);
  });

  it('takes the soonest slot still ahead among his connected channels, never a stale or unconnected one', () => {
    const cards = characterCards(
      [character('franz', 'live'), character('reginald', 'live'), character('lenny', 'designing')],
      [
        channel('franz', 'instagram', { next_slot: ahead(30) }),
        channel('franz', 'tiktok', { next_slot: ahead(6) }),
        channel('reginald', 'tiktok', { next_slot: ahead(-3) }), // behind us: stale
        channel('reginald', 'instagram', { next_slot: ahead(2), connected: false }), // not linked: cannot post
        channel('lenny', 'tiktok'), // no slot yet
      ],
      NOW,
    );
    expect(cards.map((c) => [c.slug, c.nextSlot])).toEqual([['franz', ahead(6)], ['reginald', null], ['lenny', null]]);
  });

  it('lists the handles instagram first, the seeded ones, else the planned ones until the account exists', () => {
    const [franz, lenny, none] = characterCards(
      [
        character('franz', 'live', { accounts: [
          { platform: 'tiktok', handle: ' @franz ', has_postiz: true, mode: 'approval' },
          { platform: 'instagram', handle: 'franz.ig', has_postiz: true, mode: 'approval' },
          { platform: 'tiktok', handle: '', has_postiz: false, mode: 'approval' },
        ] }),
        character('lenny', 'designing', { setup: { planned_handles: { instagram: 'lenny.gold', tiktok: '@lenny' } }, accounts: [
          { platform: 'tiktok', handle: '@lennygold', has_postiz: false, mode: 'approval' },
        ] }),
        character('zed', 'designing'),
      ],
      [],
      NOW,
    );
    expect(franz.handles).toEqual([{ platform: 'instagram', handle: 'franz.ig', planned: false }, { platform: 'tiktok', handle: '@franz', planned: false }]);
    expect(lenny.handles).toEqual([{ platform: 'instagram', handle: 'lenny.gold', planned: true }, { platform: 'tiktok', handle: '@lennygold', planned: false }]);
    expect(none.handles).toEqual([]);
  });
});
