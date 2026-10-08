import { existsSync, readFileSync } from 'node:fs';
import { describe, expect, it } from 'vitest';
import {
  blocks, boldQuote, cdnPrefix, edition, firstParagraph, listItems, parseArtist, plannedHandle, section, table, voiceOf,
} from '../../scripts/bible.mjs';
import generated from '../generated/artists.json';
import { artistAccounts, artistVideos, findArtist, inlineParts, swapLine, type Artist } from './artist';
import { href, parseHash } from './hooks';
import type { Character } from './types';

const repo = (path: string) => new URL(`../../../${path}`, import.meta.url);
const read = (path: string) => (existsSync(repo(path)) ? readFileSync(repo(path), 'utf8') : '');
const ARTISTS = (generated as unknown as { artists: Artist[] }).artists;

const BIBLE = `# Testy — character bible

**Status:** designing.
**Concept:** a **test** character.

## Look lock (head to toe)
- **Hair:** short.
- **Eyes:** odd,
  one blue and one amber.

## Wardrobe
**Brand rule:** no brands.

**Signature outfit (head to toe), as in the master:**
- **Coat:** red.
- **Paste-ready line:** "wearing a red coat".

**Capsule (alternate outfits):**
1. **Testy: rain** (idea). A mac.
2. **Testy: gym** (ready). A headband.

## Signature move (locked by the owner 2026-10-06)
**The Nod:** he nods once.
- Alternative: a wink.

## Catchphrase (locked)
**"Quite so."** Use it in the first comment.

## Motion
- **Walk:** brisk.
- **Signature move:** the Nod (above).

## How he talks
- **Voice:** Higgsfield preset **Basil**, \`voice_id 11111111-2222-3333-4444-555555555555\` (test file \`hf_20261006_043131_892db83e-6d5e-4b2e-abca-ad998634b223.wav\`).
- **Sample lines:**
  - "One."
  - "Two."

## Voice (captions)
Dry. Title: \`<famous moment or format> · test edition\`.

## Gadgets ready
| Gadget | Status | Where | Viral job |
|---|---|---|---|
| **Umbrella** | **ready** | panel 1 | The rain gag |
| Hat | idea | — | Nothing yet |

## Swap rule
Like for like: **Testy replaces a person**.
`;

const REFS = {
  slug: 'testy', name: 'Testy', status: 'designing', bodies: ['biped'],
  reference_urls: { master_biped: 'https://cdn.example/u/master.png', sheet_biped: 'https://cdn.example/u/sheet.png' },
  swap: { noun: 'tester', stars: ['person'] },
  accounts: [{ platform: 'instagram', handle: 'testy.ig', planned_handle: 'testy.ig', postiz_integration_id: 'abc' }],
  traits: { props: [{ name: 'umbrella', job: 'rain' }] },
};

describe('the bible parser (scripts/bible.mjs)', () => {
  it('finds a section by the start of its heading and reads its list, nested lines and continuations', () => {
    expect(section(BIBLE, 'Signature move')).toMatch(/^\*\*The Nod:\*\*/);
    expect(section(BIBLE, 'nothing like it')).toBe('');
    expect(listItems(section(BIBLE, 'Look lock'))).toEqual([
      { text: '**Hair:** short.' }, { text: '**Eyes:** odd, one blue and one amber.' },
    ]);
    expect(listItems(section(BIBLE, 'How he talks'))[1]).toEqual({ text: '**Sample lines:**', children: [{ text: '"One."' }, { text: '"Two."' }] });
    expect(firstParagraph(section(BIBLE, 'Signature move'))).toBe('**The Nod:** he nods once.');
  });

  it('splits the wardrobe into its bold-led blocks and reads tables, quotes, the edition and the voice', () => {
    expect(blocks(section(BIBLE, 'Wardrobe')).map((b) => [b.label, b.items.length])).toEqual([
      ['Brand rule', 0], ['Signature outfit (head to toe), as in the master', 2], ['Capsule (alternate outfits)', 2],
    ]);
    expect(table(section(BIBLE, 'Gadgets ready'))).toEqual([
      { Gadget: '**Umbrella**', Status: '**ready**', Where: 'panel 1', 'Viral job': 'The rain gag' },
      { Gadget: 'Hat', Status: 'idea', Where: '—', 'Viral job': 'Nothing yet' },
    ]);
    expect(boldQuote(section(BIBLE, 'Catchphrase'))).toBe('Quite so.');
    expect(edition(section(BIBLE, 'Voice (captions)'))).toBe('test');
    expect(voiceOf(section(BIBLE, 'How he talks'))).toEqual({
      preset: 'Basil', voice_id: '11111111-2222-3333-4444-555555555555', sample_file: 'hf_20261006_043131_892db83e-6d5e-4b2e-abca-ad998634b223.wav',
    });
    expect(cdnPrefix(REFS, '')).toBe('https://cdn.example/u/');
    expect(cdnPrefix({}, 'CDN prefix `https://d.example/x/`.')).toBe('https://d.example/x/');
    expect(plannedHandle('## Handles (try in order)\n1. `franz.dachshund`\n2. `lord.franz`')).toBe('franz.dachshund');
    expect(plannedHandle('no kit')).toBeNull();
  });

  it('builds the artist card: local copies when the build made them, the CDN otherwise, the gadgets with their job', () => {
    const a = parseArtist(REFS, BIBLE, '## Handles\n1. `testy.go`', { turnaround: true });
    expect(a).toMatchObject({ slug: 'testy', name: 'Testy', status: 'designing', concept: 'a **test** character.', edition: 'test' });
    expect(a.images).toEqual({
      spec: null, turnaround: '/artists/testy/turnaround.jpg', avatar: null,
      turnaround_url: 'https://cdn.example/u/sheet.png', master_url: 'https://cdn.example/u/master.png',
    });
    expect(a.wardrobe.signature.map((i) => i.text)).toEqual(['**Coat:** red.']); // the paste-ready prompt line is left out
    expect(a.wardrobe.capsule).toHaveLength(2);
    expect(a.motion.map((i) => i.text)).toEqual(['**Walk:** brisk.']); // the pointer to the signature move is not repeated
    expect(a.signature_move).toEqual({ text: '**The Nod:** he nods once.', notes: [{ text: 'Alternative: a wink.' }] });
    expect(a.catchphrase.line).toBe('Quite so.');
    expect(a.voice).toMatchObject({ preset: 'Basil', sample_url: 'https://cdn.example/u/hf_20261006_043131_892db83e-6d5e-4b2e-abca-ad998634b223.wav' });
    expect(a.gadgets).toEqual([{ name: 'Umbrella', status: 'ready', job: 'The rain gag' }, { name: 'Hat', status: 'idea', job: 'Nothing yet' }]);
    expect(a.swap).toEqual({ text: 'Like for like: **Testy replaces a person**.', noun: 'tester', stars: ['person'] });
    expect(a.accounts).toEqual([
      { platform: 'instagram', handle: 'testy.ig', planned: 'testy.ig', connected: true },
      { platform: 'tiktok', handle: null, planned: '@testy.go', connected: false }, // social.md's handle, TikTok with its @
    ]);
  });

  it('takes a folder with refs.json only (a new character before his bible): the traits gadgets, empty sections', () => {
    const a = parseArtist({ slug: 'newbie', name: 'Newbie', traits: { props: ['hat', { name: 'cane', job: 'the bow' }] } });
    expect(a.gadgets).toEqual([{ name: 'hat', status: null, job: null }, { name: 'cane', status: null, job: 'the bow' }]);
    expect([a.look, a.motion, a.voice.items, a.catchphrase.line, a.swap.text, a.images.turnaround_url]).toEqual([[], [], [], null, null, null]);
    expect(a.accounts.map((x) => x.planned)).toEqual([null, null]);
  });

  it('reads the real roster bibles (owner 2026-10-06)', () => {
    for (const [slug, phrase, preset, sample] of [
      ['franz', 'Sausage coming through!', 'Alistair', true], ['reginald', 'As you were.', null, false], ['lenny', 'You’re welcome.', 'Emmett', true],
    ] as const) {
      const refs = JSON.parse(read(`characters/${slug}/refs.json`));
      const a = parseArtist(refs, read(`characters/${slug}/bible.md`), read(`characters/${slug}/social.md`));
      expect([slug, a.catchphrase.line?.replace('’', '’').replace("'", '’')]).toEqual([slug, phrase]);
      expect([slug, a.voice.preset, Boolean(a.voice.sample_url)]).toEqual([slug, preset, sample]);
      expect([slug, a.look.length >= 5, a.wardrobe.signature.length >= 3, a.wardrobe.capsule.length >= 3, a.motion.length >= 4]).toEqual([slug, true, true, true, true]);
      expect([slug, a.gadgets.length >= 5, a.gadgets.every((g) => g.name && g.job)]).toEqual([slug, true, true]);
      expect([slug, Boolean(a.signature_move.text && a.swap.text && a.images.turnaround_url)]).toEqual([slug, true]);
    }
  });
});

describe('the generated artists.json', () => {
  it('has a card for every character of the roster, with the page’s sections', () => {
    for (const slug of ['franz', 'reginald', 'lenny']) {
      const a = findArtist(slug, ARTISTS);
      expect(a, slug).not.toBeNull();
      expect([slug, a!.look.length > 0, a!.gadgets.length > 0, Boolean(a!.catchphrase.line), a!.accounts.length]).toEqual([slug, true, true, true, 2]);
    }
    expect(findArtist('nobody', ARTISTS)).toBeNull();
    expect(findArtist(null, ARTISTS)).toBeNull();
  });
});

describe('the artist page helpers', () => {
  it('keeps the bold and code of a bible line and drops link targets', () => {
    expect(inlineParts('**Tailcoat:** black `#151517` wool, see [the doc](x.md).')).toEqual([
      { kind: 'strong', text: 'Tailcoat:' }, { kind: 'text', text: ' black ' }, { kind: 'code', text: '#151517' },
      { kind: 'text', text: ' wool, see the doc.' },
    ]);
    expect(inlineParts('plain')).toEqual([{ kind: 'text', text: 'plain' }]);
    expect(swapLine(['dog'])).toBe('Replaces a dog');
    expect(swapLine(['person', 'animal'])).toBe('Replaces a person or a small animal');
    expect(swapLine([])).toBeNull();
  });

  it('shows the seeded accounts first, then what is planned', () => {
    const card = parseArtist({ ...REFS, accounts: [] }, '', '## Handles\n1. `testy.go`');
    const seeded: Pick<Character, 'accounts' | 'setup'> = {
      accounts: [
        { platform: 'instagram', handle: 'testy.ig', has_postiz: true, mode: 'approval' },
        { platform: 'tiktok', handle: '@testy', has_postiz: false, mode: 'approval' },
      ],
      setup: {},
    };
    expect(artistAccounts(card, seeded)).toEqual([
      { platform: 'instagram', handle: 'testy.ig', state: 'live' }, { platform: 'tiktok', handle: '@testy', state: 'linked' },
    ]);
    expect(artistAccounts(card, { accounts: [], setup: { planned_handles: { instagram: 'from.seed' } } })).toEqual([
      { platform: 'instagram', handle: 'from.seed', state: 'planned' }, { platform: 'tiktok', handle: '@testy.go', state: 'planned' },
    ]);
    expect(artistAccounts(parseArtist(REFS), null)[0]).toEqual({ platform: 'instagram', handle: 'testy.ig', state: 'live' }); // not seeded yet
  });

  it('lists his videos from what the terminal loads: in the works, waiting for the owner, posted, with the numbers', async () => {
    const NOW = Date.parse('2026-10-06T12:00:00Z');
    const { DemoBackend } = await import('../demo/backend');
    const snap = await new DemoBackend(() => NOW).load();
    const franz = artistVideos('franz', snap, NOW);
    expect(franz.stats).toMatchObject({ inTheWorks: 2, waiting: 0, posted: 0, views: null, bestX: null, creditsMonth: 0 });
    expect(franz.works.map((v) => v.where).sort()).toEqual(['Checking', 'Ready']); // his two drops, named as In the works names them
    expect(franz.works.some((v) => v.title === 'Your video')).toBe(true); // never the internal owner-drop: key
    const biscuit = artistVideos('biscuit', snap, NOW);
    expect(biscuit.stats.posted).toBeGreaterThan(3);
    expect(biscuit.posted[0].route).toBe('library');
    expect(Date.parse(biscuit.posted[0].where)).toBeGreaterThanOrEqual(Date.parse(biscuit.posted[1].where)); // newest first
    expect(biscuit.stats.views).toBe(biscuit.posted.reduce((s, v) => s + (v.views ?? 0), 0));
    expect(biscuit.stats.bestX).toBe(Math.max(...biscuit.posted.map((v) => v.outlierX ?? -1)));
    expect(biscuit.queue.every((v) => v.route === 'queue' && v.where === 'Your OK')).toBe(true);
    expect(artistVideos('nobody', snap, NOW).stats).toMatchObject({ inTheWorks: 0, waiting: 0, posted: 0 });
  });

  it('is reached at #/artist/<slug>', () => {
    expect(parseHash('#/artist/franz')).toEqual({ route: 'artist', param: 'franz', query: '' });
    expect(href('artist', 'lenny')).toBe('#/artist/lenny');
  });
});
