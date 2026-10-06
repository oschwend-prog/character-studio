import { describe, expect, it } from 'vitest';
import { ROSTER, activeRoster, isPaused, liveryClass, nameOf, orderRoster } from './roster';

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
