// The pick card and the Picks page: tiers, grouping by character, themes, the picture, gadgets, music, the estimate,
// the attached clip, the character switcher. Pure rules, tested without a browser.
import { readFileSync } from 'node:fs';
import { describe, expect, it } from 'vitest';
import { DemoBackend } from '../demo/backend';
import { pickFacts } from './analyst';
import traitsJson from '../demo/traits.json';
import { href, parseHash } from './hooks';
import parity from './parity-cases.json';
import {
  CHARACTER_FILTER_KEY, CLIP_MAX_BYTES, CLIP_MAX_SECONDS, CREDITS, DEFAULT_MUSIC, NO_THEME, ORIGINAL_AUDIO_NOTE, PROPS_MAX,
  PROP_MAX_CHARS, RECREATE_NO_ORIGINAL, TIERS, TIER_LABELS, UNASSIGNED_NAME, characterFilterOptions, checkClipBasics, defaultMusicForMode,
  defaultTier, effectiveMode, estimateCredits, gadgetList, hasUsableSource, noClipNote, groupPicksByCharacter, loadCharacterFilter, makeItPayload, modeLine, musicOptionsFor,
  ownerClipPath, parseCharacterFilter, pipelineFor, rankPicks, saveCharacterFilter, sheetEstimate, thumbFor,
  tierCounts, tierOf, traitProps, traitRows, validateClipFile,
  type PickCardLike,
} from './rules';
import type { CharacterTraits, Tier } from './types';

const NOW = Date.parse(parity.now);
const DAY = 86_400_000;
const ago = (days: number) => new Date(NOW - days * DAY).toISOString();

// ---- tiers -----------------------------------------------------------------------------------------------------

describe('the four tiers', () => {
  it('have exactly the owner’s keys and labels, in the order the page groups them', () => {
    expect(TIERS).toEqual(['iconic', 'viral_now', 'rising', 'gallery']);
    expect(TIER_LABELS).toEqual({ iconic: 'Broke the internet', viral_now: 'Viral now', rising: 'Up and coming', gallery: 'Ready to drop in' });
  });
});

describe('defaultTier (the same cases as studio.favorites.default_tier)', () => {
  it('agrees with every shared case', () => {
    expect(parity.tier.length).toBeGreaterThanOrEqual(25);
    for (const c of parity.tier) {
      const got = defaultTier(
        {
          gallery: c.gallery, outlier_x: c.outlier_x, views: c.views, velocity: 'velocity' in c ? c.velocity : null,
          posted_at: c.days_ago == null ? null : ago(c.days_ago),
        },
        NOW,
      );
      expect([JSON.stringify(c), got]).toEqual([JSON.stringify(c), c.expect]);
    }
  });

  it('tierOf takes the analyst’s tier and says when it derived one', () => {
    expect(tierOf({ tier: 'iconic', outlier_x: 3, posted_at: ago(1) }, NOW)).toEqual({ tier: 'iconic', derived: false });
    expect(tierOf({ tier: 'rising', outlier_x: 500, posted_at: ago(400), views: 90_000_000 }, NOW)).toEqual({ tier: 'rising', derived: false }); // explicit wins
    expect(tierOf({ tier: null, outlier_x: 3, posted_at: ago(100) }, NOW)).toEqual({ tier: 'iconic', derived: true });
    expect(tierOf({ tier: 'nonsense', outlier_x: 150, posted_at: ago(1) }, NOW)).toEqual({ tier: 'viral_now', derived: true });
    expect(tierOf({ outlier_x: 9, gallery: true }, NOW)).toEqual({ tier: 'gallery', derived: true });
  });

  it('an unreadable post date is an unknown one', () => {
    expect(defaultTier({ outlier_x: 500, posted_at: 'not a date' }, NOW)).toBe('viral_now');
  });
});

// ---- grouping by character ----------------------------------------------------------------------------------------

const ROSTER = [{ slug: 'biscuit', name: 'Biscuit' }, { slug: 'reginald', name: 'Reginald' }];
const card = (id: string, over: Partial<PickCardLike> = {}): PickCardLike => ({
  id, character_slug: 'biscuit', total_score: 70, created_at: '2026-10-05T08:00:00Z', outlier_x: 150, posted_at: ago(2), tier: null, gallery: false, theme: null, ...over,
});

describe('rankPicks', () => {
  it('real clips by score, unscored last, older first on a tie, and the gallery clips after all of them', () => {
    const ranked = rankPicks([
      card('gallery-high', { gallery: true, total_score: 99 }),
      card('low', { total_score: 60 }),
      card('none', { total_score: null }),
      card('high', { total_score: 90 }),
      card('tie-new', { total_score: 80, created_at: '2026-10-05T09:00:00Z' }),
      card('tie-old', { total_score: 80, created_at: '2026-10-05T07:00:00Z' }),
      card('gallery-low', { tier: 'gallery', total_score: 50 }),
    ], NOW);
    expect(ranked.map((p) => p.id)).toEqual(['high', 'tie-old', 'tie-new', 'low', 'none', 'gallery-high', 'gallery-low']);
  });
});

describe('groupPicksByCharacter', () => {
  const picks = [
    card('b-hi', { total_score: 88 }),
    card('b-icon', { tier: 'iconic', total_score: 60 }),
    card('b-gal', { gallery: true, total_score: 95, theme: 'dog leads the dancers' }),
    card('b-rise', { outlier_x: 12, views: 40_000, posted_at: ago(1), total_score: 72, theme: 'pet with a human job' }),
    card('r-1', { character_slug: 'reginald', total_score: 81, theme: 'deadpan at work' }),
    card('r-2', { character_slug: 'reginald', total_score: 77, theme: 'deadpan at work' }),
    card('r-3', { character_slug: 'reginald', total_score: 90, theme: 'elder out-dances the young' }),
    card('o-1', { character_slug: null, total_score: 55 }),
    card('o-2', { character_slug: 'someone-not-seeded', total_score: 65 }),
  ];

  it('one section per character in roster order, then Unassigned (no character yet) at the bottom', () => {
    const sections = groupPicksByCharacter(picks, ROSTER, { now: NOW });
    expect(sections.map((s) => [s.slug, s.name])).toEqual([['biscuit', 'Biscuit'], ['reginald', 'Reginald'], [null, UNASSIGNED_NAME]]);
    expect(UNASSIGNED_NAME).toBe('Unassigned (no character yet)');
    expect(sections[2].picks.map((p) => p.id)).toEqual(['o-2', 'o-1']); // a slug nobody seeded is unassigned too, best first
  });

  it('inside a character the picks are best first, with the gallery ones last whatever their score', () => {
    const [biscuit] = groupPicksByCharacter(picks, ROSTER, { now: NOW });
    expect(biscuit.picks.map((p) => p.id)).toEqual(['b-hi', 'b-rise', 'b-icon', 'b-gal']);
  });

  it('groups by tier in the owner’s order and leaves empty tiers out; the gallery tier is always the last group', () => {
    const [biscuit, reginald] = groupPicksByCharacter(picks, ROSTER, { now: NOW });
    expect(biscuit.tiers.map((g) => [g.tier, g.label, g.picks.map((p) => p.id)])).toEqual([
      ['iconic', 'Broke the internet', ['b-icon']],
      ['viral_now', 'Viral now', ['b-hi']],
      ['rising', 'Up and coming', ['b-rise']],
      ['gallery', 'Ready to drop in', ['b-gal']],
    ]);
    expect(reginald.tiers.map((g) => g.tier)).toEqual(['viral_now']); // nothing else has a card
  });

  it('groups by theme: the best real clip’s theme first, gallery-only themes after, no theme last', () => {
    const [biscuit, reginald] = groupPicksByCharacter(picks, ROSTER, { now: NOW });
    expect(biscuit.themes.map((g) => [g.theme, g.label, g.picks.map((p) => p.id)])).toEqual([
      ['pet with a human job', 'pet with a human job', ['b-rise']],
      ['dog leads the dancers', 'dog leads the dancers', ['b-gal']], // only a gallery clip: after the real themes
      [null, NO_THEME, ['b-hi', 'b-icon']], // no theme recorded: last of all, even with the best score
    ]);
    expect(reginald.themes.map((g) => [g.theme, g.picks.map((p) => p.id)])).toEqual([
      ['elder out-dances the young', ['r-3']], // 90 beats 81
      ['deadpan at work', ['r-1', 'r-2']],
    ]);
  });

  it('a character with no picks is still a section (empty), and a section is never invented for nobody', () => {
    const sections = groupPicksByCharacter([card('only-biscuit')], ROSTER, { now: NOW });
    expect(sections.map((s) => [s.slug, s.picks.length])).toEqual([['biscuit', 1], ['reginald', 0]]);
    expect(sections[1].tiers).toEqual([]);
    expect(groupPicksByCharacter([], ROSTER, { now: NOW }).map((s) => s.slug)).toEqual(['biscuit', 'reginald']);
  });

  it('the character filter keeps one section (and no unassigned one); all and unknown keep everything', () => {
    expect(groupPicksByCharacter(picks, ROSTER, { now: NOW, character: 'reginald' }).map((s) => s.slug)).toEqual(['reginald']);
    expect(groupPicksByCharacter(picks, ROSTER, { now: NOW, character: 'all' })).toHaveLength(3);
    expect(groupPicksByCharacter(picks, ROSTER, { now: NOW, character: 'nobody' })).toHaveLength(3);
  });

  it('the tier filter keeps one tier’s picks and the counts follow', () => {
    const rising = groupPicksByCharacter(picks, ROSTER, { now: NOW, tier: 'rising' });
    expect(rising.map((s) => s.picks.map((p) => p.id))).toEqual([['b-rise'], []]); // Biscuit's, Reginald's (none), and no unassigned section
    expect(groupPicksByCharacter(picks, ROSTER, { now: NOW, tier: 'all' })[0].picks).toHaveLength(4);
  });

  it('tierCounts counts each tier and all', () => {
    expect(tierCounts(picks, NOW)).toEqual({ all: 9, iconic: 1, viral_now: 6, rising: 1, gallery: 1 });
  });

  it('does not change the picks it is given', () => {
    const copy = JSON.stringify(picks);
    groupPicksByCharacter(picks, ROSTER, { now: NOW });
    expect(JSON.stringify(picks)).toBe(copy);
  });
});

// ---- the picture ----------------------------------------------------------------------------------------------------

const base = { platform: 'tiktok', creator_handle: '@eatfryhaven', hook: 'first day', url: 'https://www.tiktok.com/@eatfryhaven/video/1' };

describe('thumbFor', () => {
  it('shows the thumbnail when there is a usable https image, with an alt text naming the video', () => {
    const t = thumbFor({ ...base, thumbnail_url: 'https://d1.cloudfront.net/g/abc.jpg' });
    expect(t).toMatchObject({ kind: 'image', src: 'https://d1.cloudfront.net/g/abc.jpg', aspect: '9:16', preview: null, code: 'TT', original: base.url });
    expect(t.alt).toBe('Thumbnail of “first day” on TikTok by @eatfryhaven');
  });

  it('falls back to a platform tile when there is no thumbnail, an insecure or malformed one, or the image failed to load', () => {
    for (const thumbnail_url of [null, undefined, '', 'http://cdn.example.com/a.jpg', 'javascript:alert(1)', 'not a url', 'https://', '//cdn.example.com/a.jpg', 'https://a b.com/x.jpg']) {
      const t = thumbFor({ ...base, thumbnail_url });
      expect(t).toMatchObject({ kind: 'placeholder', src: null, platform: 'tiktok', code: 'TT', handle: '@eatfryhaven', original: base.url });
      expect(t.alt).toMatch(/^Placeholder of “first day”/);
    }
    // platform CDN thumbnails expire: a good URL whose image failed to load is the same tile
    expect(thumbFor({ ...base, thumbnail_url: 'https://p16.tiktokcdn.com/x.jpg' }, { imageFailed: true })).toMatchObject({ kind: 'placeholder', src: null });
  });

  it('keeps a valid https preview video (mp4/webm/mov/m4v) whether or not the picture shows, and drops anything else', () => {
    expect(thumbFor({ ...base, thumbnail_url: 'https://t.example/a.jpg', preview_url: 'https://t.example/a.mp4?Expires=1&Signature=x' }).preview).toBe('https://t.example/a.mp4?Expires=1&Signature=x');
    expect(thumbFor({ ...base, preview_url: 'https://t.example/a.webm' })).toMatchObject({ kind: 'placeholder', preview: 'https://t.example/a.webm' });
    for (const preview_url of [null, 'http://t.example/a.mp4', 'https://t.example/a.png', 'https://t.example/page.html', 'javascript:1']) {
      expect(thumbFor({ ...base, thumbnail_url: 'https://t.example/a.jpg', preview_url }).preview).toBeNull();
    }
  });

  it('an inline image (the demo’s) is fine, an inline anything else is not', () => {
    expect(thumbFor({ ...base, thumbnail_url: 'data:image/svg+xml;utf8,%3Csvg%3E' }).kind).toBe('image');
    expect(thumbFor({ ...base, thumbnail_url: 'data:text/html,<script>1</script>' }).kind).toBe('placeholder');
  });

  it('a YouTube pick is 16:9 (letterboxed in the 9:16 frame) and so is a ytimg thumbnail', () => {
    expect(thumbFor({ ...base, platform: 'youtube', thumbnail_url: 'https://i.ytimg.com/vi/abc/hqdefault.jpg' })).toMatchObject({ aspect: '16:9', code: 'YT' });
    expect(thumbFor({ ...base, thumbnail_url: 'https://i.ytimg.com/vi/abc/hqdefault.jpg' }).aspect).toBe('16:9');
  });

  it('a Genjutsu gallery pick has a preview and no page to view: it is keyed by its preset', () => {
    const t = thumbFor({
      platform: 'higgsfield', creator_handle: null, hook: 'tea for two', url: 'higgsfield-preset:hf-1',
      thumbnail_url: 'https://d1.cloudfront.net/t/a.jpg', preview_url: 'https://d1.cloudfront.net/p/a.mp4',
    });
    expect(t).toMatchObject({ kind: 'image', code: 'HF', original: null, preview: 'https://d1.cloudfront.net/p/a.mp4' });
    expect(t.alt).toBe('Thumbnail of “tea for two” on the Genjutsu gallery');
    expect(thumbFor({ platform: 'higgsfield', creator_handle: null, hook: null, url: 'higgsfield-preset:hf-1' })).toMatchObject({ kind: 'placeholder', original: null });
  });

  it('names the video by its creator when it has no hook, and never invents a platform', () => {
    expect(thumbFor({ ...base, hook: null }).alt).toBe('Placeholder of @eatfryhaven on TikTok by @eatfryhaven');
    expect(thumbFor({ ...base, platform: 'myspace', creator_handle: null, hook: null })).toMatchObject({ code: '??', platform: 'other', handle: null });
  });
});

describe('modeLine (the top line of a card)', () => {
  it('says Drop-in with his part, Recreate, or that the analyst decides; the owner’s choice wins', () => {
    expect(modeLine({ proposed_mode: 'dropin', owner_mode: null, owner_presence: null })).toBe('Drop-in · his part: featured');
    expect(modeLine({ proposed_mode: 'dropin', owner_mode: 'dropin', owner_presence: 'star' })).toBe('Drop-in · his part: star');
    expect(modeLine({ proposed_mode: 'dropin', owner_mode: 'recreate' })).toBe('Recreate');
    expect(modeLine({ proposed_mode: 'recreate' })).toBe('Recreate');
    expect(modeLine({ proposed_mode: null })).toBe('Analyst decides how to make it');
  });
});

// ---- gadgets & jewellery ---------------------------------------------------------------------------------------------------

describe('gadgetList', () => {
  it('trims, drops blanks and repeats, and keeps the order: the chips first, then the free one', () => {
    expect(gadgetList([' gold chain ', 'Gold Chain', 'shades'], ' tiny crown ')).toEqual({ ok: true, items: ['gold chain', 'shades', 'tiny crown'] });
    expect(gadgetList([], '   ')).toEqual({ ok: true, items: [] });
  });

  it('allows at most 3 items of at most 40 characters', () => {
    expect([PROPS_MAX, PROP_MAX_CHARS]).toEqual([3, 40]);
    expect(gadgetList(['a', 'b', 'c'], '')).toMatchObject({ ok: true });
    expect(gadgetList(['a', 'b', 'c'], 'd')).toEqual({ ok: false, reason: 'Pick at most 3 gadgets (now 4)' });
    expect(gadgetList(['a', 'a', 'A', 'b', 'c'], '')).toMatchObject({ ok: true }); // repeats are one
    expect(gadgetList([], 'x'.repeat(40))).toMatchObject({ ok: true });
    expect(gadgetList([], 'x'.repeat(41))).toMatchObject({ ok: false });
  });
});

describe('traitProps and traitRows', () => {
  const traits: CharacterTraits = {
    energy: 'calm', comedy: 'deadpan', best_formats: ['f1'], settings: ['s1'], moves: ['m1'],
    props: ['feather duster', { name: 'gold pocket watch', job: '"4pm. tea." timing gags' }], music: 'orchestral', never: ['smiling'],
  };

  it('a prop is a phrase or a name with its viral job; both become chips', () => {
    expect(traitProps(traits)).toEqual([{ name: 'feather duster', job: null }, { name: 'gold pocket watch', job: '"4pm. tea." timing gags' }]);
    expect(traitProps(null)).toEqual([]);
  });

  it('the Traits card rows are in reading order, with a job as the chip’s hint, and a character without a card has none', () => {
    const rows = traitRows(traits);
    expect(rows.map((r) => [r.label, r.kind])).toEqual([
      ['Energy', 'text'], ['Comedy', 'text'], ['Best formats', 'chips'], ['Settings', 'chips'], ['Moves', 'chips'],
      ['Gadgets & jewellery', 'chips'], ['Music', 'text'], ['Never', 'chips'],
    ]);
    expect(rows[5].values).toEqual([{ text: 'feather duster' }, { text: 'gold pocket watch', hint: '"4pm. tea." timing gags' }]);
    expect(traitRows(null)).toEqual([]);
    expect(traitRows({ ...traits, props: [] }).map((r) => r.label)).not.toContain('Gadgets & jewellery');
  });

  it('the demo’s traits cards are the real refs.json ones, so the demo cannot drift from what the seed writes', () => {
    for (const slug of ['franz', 'reginald', 'lenny', 'biscuit']) {
      const refs = JSON.parse(readFileSync(new URL(`../../../characters/${slug}/refs.json`, import.meta.url), 'utf8')) as { traits: CharacterTraits };
      expect((traitsJson as Record<string, CharacterTraits>)[slug]).toEqual(refs.traits);
      expect(traitProps(refs.traits).length).toBeGreaterThanOrEqual(7);
      expect(traitProps(refs.traits).every((p) => p.name.length <= PROP_MAX_CHARS && p.job)).toBe(true); // a chip, and what it is for
    }
  });
});

// ---- music and the estimate -----------------------------------------------------------------------------------------------------

describe('music', () => {
  it('Drop-ins keep the original audio by default; a Recreate keeps its own driver’s beat', () => {
    expect(DEFAULT_MUSIC).toBe('original');
    expect(defaultMusicForMode('dropin')).toBe('original');
    expect(defaultMusicForMode('analyst')).toBe('original');
    expect(defaultMusicForMode('recreate')).toBe('ai_beat');
  });

  it('a Drop-in offers the three options in the owner’s words; the original one carries the small grey note', () => {
    const options = musicOptionsFor('dropin');
    expect(options.map((o) => [o.id, o.name])).toEqual([
      ['original', 'Keep original audio (default)'], ['in_app', 'Add in Instagram app'], ['ai_beat', 'AI beat (+30)'],
    ]);
    expect(options[0].note).toBe(ORIGINAL_AUDIO_NOTE);
    expect(ORIGINAL_AUDIO_NOTE).toBe('If Instagram mutes a chart song, re-post with the song added in-app.');
    expect(options.slice(1).every((o) => o.note === undefined)).toBe(true);
    expect(musicOptionsFor('analyst')).toEqual(options);
  });

  it('a Recreate has no original audio: it offers the AI beat (default) and the in-app song', () => {
    expect(musicOptionsFor('recreate').map((o) => o.id)).toEqual(['ai_beat', 'in_app']);
  });
});

describe('estimateCredits (the same cases as studio.planning.estimate_credits)', () => {
  it('agrees with every shared case', () => {
    expect(parity.credits.length).toBeGreaterThanOrEqual(8);
    for (const c of parity.credits) {
      expect([JSON.stringify(c), estimateCredits(c.mode as 'dropin' | 'recreate', c.seconds, c.music as 'in_app')]).toEqual([JSON.stringify(c), c.expect]);
    }
    expect(CREDITS).toMatchObject({ recreate: 160, dropinPerSecond: 11, stills: 3, aiBeat: 30, defaultSeconds: 8 });
  });

  it('defaults to 8 s of the original audio: 91', () => {
    expect(estimateCredits('dropin')).toBe(91);
  });
});

describe('sheetEstimate (what the Make-it sheet shows)', () => {
  it('prices the chosen options per clip and in all', () => {
    expect(sheetEstimate({ mode: 'dropin', music: 'original', clips: 1 })).toMatchObject({ perClip: 91, total: 91, label: '≈ 91 credits' });
    expect(sheetEstimate({ mode: 'dropin', music: 'in_app', clips: 1 }).total).toBe(91);
    expect(sheetEstimate({ mode: 'dropin', music: 'ai_beat', clips: 1 })).toMatchObject({ total: 121, label: '≈ 121 credits' });
    expect(sheetEstimate({ mode: 'recreate', clips: 1 })).toMatchObject({ total: 160, label: '≈ 160 credits' });
    expect(sheetEstimate({ mode: 'dropin', music: 'original', clips: 2 })).toMatchObject({ perClip: 91, total: 182, label: '≈ 182 credits (2 clips of ≈ 91)' });
  });

  it('“Analyst decides” is priced as a Drop-in and says what a Recreate would cost', () => {
    const e = sheetEstimate({ mode: 'analyst', clips: 1 });
    expect(e.total).toBe(91);
    expect(e.note).toMatch(/Recreate/);
    expect(e.note).toMatch(/160/);
  });
});

// ---- the Make-it payload: gadgets, music, the attached clip ---------------------------------------------------------------------------

describe('makeItPayload with gadgets, music and the attached clip', () => {
  const ctx = { pickCharacter: 'reginald', characters: ['biscuit', 'reginald'] };
  const choice = { character: 'reginald', note: '', mode: 'analyst' as const, presence: 'featured' as const };

  it('sends the gadgets trimmed, at most three, or nothing', () => {
    expect(makeItPayload({ ...choice, props: ['feather duster', ' handbell '], customProp: 'tiny gold chain' }, ctx)).toMatchObject({
      ok: true, extras: { ownerProps: ['feather duster', 'handbell', 'tiny gold chain'] },
    });
    expect(makeItPayload({ ...choice, props: [], customProp: '  ' }, ctx)).toMatchObject({ ok: true, extras: { ownerProps: null } });
    expect(makeItPayload({ ...choice, props: ['a', 'b', 'c'], customProp: 'd' }, ctx)).toEqual({ ok: false, reason: 'Pick at most 3 gadgets (now 4)' });
    expect(makeItPayload({ ...choice, customProp: 'x'.repeat(41) }, ctx)).toMatchObject({ ok: false });
  });

  it('sends only a music choice that differs from the default', () => {
    expect(makeItPayload({ ...choice, mode: 'dropin', music: 'original' }, { ...ctx, pick: { gallery: true } })).toMatchObject({ extras: { ownerMusic: null } });
    expect(makeItPayload({ ...choice, mode: 'dropin', music: 'in_app' }, { ...ctx, pick: { gallery: true } })).toMatchObject({ extras: { ownerMusic: 'in_app' } });
    expect(makeItPayload({ ...choice, mode: 'dropin', music: 'ai_beat' }, { ...ctx, pick: { gallery: true } })).toMatchObject({ extras: { ownerMusic: 'ai_beat' } });
    expect(makeItPayload({ ...choice, mode: 'recreate', music: 'ai_beat' }, ctx)).toMatchObject({ extras: { ownerMusic: null } }); // its default
    expect(makeItPayload({ ...choice, mode: 'recreate', music: 'in_app' }, ctx)).toMatchObject({ extras: { ownerMusic: 'in_app' } });
    expect(makeItPayload({ ...choice, music: undefined }, ctx)).toMatchObject({ extras: { ownerMusic: null } });
  });

  it('a Recreate cannot keep original audio', () => {
    expect(makeItPayload({ ...choice, mode: 'recreate', music: 'original' }, ctx)).toEqual({ ok: false, reason: RECREATE_NO_ORIGINAL });
  });

  it('an attached clip is optional: a Drop-in of a real clip without one is still confirmed, with the mode as chosen', () => {
    const real = { gallery: false, owner_clip_path: null };
    expect(makeItPayload({ ...choice, mode: 'dropin' }, { ...ctx, pick: real })).toMatchObject({ ok: true, extras: { ownerMode: 'dropin', ownerPresence: 'featured' } });
    expect(makeItPayload({ ...choice, mode: 'analyst' }, { ...ctx, pick: real })).toMatchObject({ ok: true, extras: { ownerMode: null } });
    expect(makeItPayload({ ...choice, mode: 'dropin' }, { ...ctx, pick: { ...real, owner_clip_path: 'owner/x/1.mp4' } })).toMatchObject({ ok: true });
  });
});

describe('the effective mode (what the daily run will make)', () => {
  it('a Drop-in or “analyst decides” needs a usable source: an attached clip or a Genjutsu gallery preset', () => {
    expect(hasUsableSource({ gallery: true })).toBe(true);
    expect(hasUsableSource({ gallery: false, owner_clip_path: 'owner/x/1.mp4' })).toBe(true);
    expect(hasUsableSource({ gallery: false, owner_clip_path: null }, 'owner/x/2.mp4')).toBe(true); // attached in this sheet
    expect(hasUsableSource({ gallery: false, owner_clip_path: null })).toBe(false);
    expect(hasUsableSource(undefined)).toBe(true); // nothing known: never claim a Recreate
    expect(effectiveMode('dropin', true)).toBe('dropin');
    expect(effectiveMode('analyst', true)).toBe('dropin');
    expect(effectiveMode('dropin', false)).toBe('recreate');
    expect(effectiveMode('analyst', false)).toBe('recreate');
    expect(effectiveMode('recreate', true)).toBe('recreate');
  });

  it('says so in the owner’s words, with both prices', () => {
    expect(noClipNote()).toBe(
      'No clip attached → it will be made automatically as a Recreate (≈160 credits). Attach the clip to make it a true Drop-in (≈91).',
    );
  });

  it('the cost hint follows the effective mode: 160 without a source, 91 with one', () => {
    expect(sheetEstimate({ mode: 'dropin', clips: 1, usableSource: false })).toMatchObject({ effective: 'recreate', total: 160, note: noClipNote() });
    expect(sheetEstimate({ mode: 'analyst', clips: 1, usableSource: false })).toMatchObject({ effective: 'recreate', total: 160 });
    expect(sheetEstimate({ mode: 'dropin', clips: 1, usableSource: true })).toMatchObject({ effective: 'dropin', total: 91 });
    expect(sheetEstimate({ mode: 'dropin', music: 'ai_beat', clips: 2, usableSource: true })).toMatchObject({ total: 242 });
    // the original audio does not exist for a Recreate: the estimate falls back to its own beat, never adds the Drop-in's
    expect(sheetEstimate({ mode: 'dropin', music: 'original', clips: 1, usableSource: false }).total).toBe(160);
    expect(sheetEstimate({ mode: 'recreate', clips: 1, usableSource: true })).toMatchObject({ effective: 'recreate', total: 160 });
  });
});

// ---- attaching the owner’s clip ----------------------------------------------------------------------------------------------------------

describe('validateClipFile', () => {
  const mp4 = { name: 'recording.MP4', size: 12 * 1024 * 1024, type: 'video/mp4' };

  it('takes a video of at most 200 MB and 60 s', () => {
    expect([CLIP_MAX_BYTES, CLIP_MAX_SECONDS]).toEqual([200 * 1024 * 1024, 60]);
    expect(validateClipFile(mp4, 14)).toEqual({ ok: true });
    expect(validateClipFile({ ...mp4, size: CLIP_MAX_BYTES }, 60)).toEqual({ ok: true });
    expect(validateClipFile({ ...mp4, size: CLIP_MAX_BYTES + 1 }, 14)).toMatchObject({ ok: false, reason: expect.stringContaining('200 MB') });
    expect(validateClipFile(mp4, 60.5)).toMatchObject({ ok: false, reason: expect.stringContaining('60 s') });
  });

  it('an iPhone camera-roll clip is video/quicktime or has no type at all: the extension counts too', () => {
    expect(validateClipFile({ name: 'IMG_1234.MOV', size: 5e6, type: 'video/quicktime' }, 10)).toEqual({ ok: true });
    expect(validateClipFile({ name: 'IMG_1234.mov', size: 5e6, type: '' }, 10)).toEqual({ ok: true });
    expect(validateClipFile({ name: 'photo.jpg', size: 5e6, type: 'image/jpeg' }, 10)).toMatchObject({ ok: false });
    expect(validateClipFile({ name: 'notes.txt', size: 5, type: 'text/plain' }, 10)).toMatchObject({ ok: false });
  });

  it('refuses an empty file and a video the browser could not read', () => {
    expect(validateClipFile({ ...mp4, size: 0 }, 10)).toMatchObject({ ok: false });
    for (const duration of [null, 0, -3, Number.NaN, Number.POSITIVE_INFINITY]) expect(validateClipFile(mp4, duration)).toMatchObject({ ok: false });
    expect(checkClipBasics(mp4)).toEqual({ ok: true }); // size and type alone need no video element
  });
});

describe('ownerClipPath', () => {
  const id = '3f2b8c1e-5d4a-4e6f-9a7b-0c1d2e3f4a5b';

  it('is owner/<pick id>/<timestamp>.<ext>, exactly what attach_clip and the storage policy accept', () => {
    const path = ownerClipPath(id, { name: 'My Recording.MOV', type: 'video/quicktime' }, 1_759_660_000_123.9);
    expect(path).toBe(`owner/${id}/1759660000123.mov`);
    expect(path).toMatch(new RegExp(`^owner/${id}/[^/\\s]+$`)); // the regex of studio.attach_clip
  });

  it('never trusts the file name: only a known video extension survives, and the pick id must be a uuid', () => {
    expect(ownerClipPath(id, { name: '../../etc/passwd', type: 'video/mp4' }, 5)).toBe(`owner/${id}/5.mp4`);
    expect(ownerClipPath(id, { name: 'clip', type: 'video/quicktime' }, 5)).toBe(`owner/${id}/5.mov`);
    expect(ownerClipPath(id.toUpperCase(), { name: 'a.webm', type: '' }, 5)).toBe(`owner/${id}/5.webm`);
    expect(() => ownerClipPath('../x', { name: 'a.mp4', type: '' }, 5)).toThrow(/not a pick id/);
    expect(() => ownerClipPath('', { name: 'a.mp4', type: '' }, 5)).toThrow();
  });
});

// ---- the character switcher ------------------------------------------------------------------------------------------------------------------

describe('the character switcher', () => {
  const known = ['biscuit', 'reginald'];
  const store = (value: string | null) => ({ getItem: (k: string) => (k === CHARACTER_FILTER_KEY ? value : null) });

  it('offers Biscuit · Reginald · All', () => {
    expect(characterFilterOptions(ROSTER)).toEqual([{ id: 'biscuit', label: 'Biscuit' }, { id: 'reginald', label: 'Reginald' }, { id: 'all', label: 'All' }]);
  });

  it('opens on All, on what this viewer chose last time, or on a ?c= deep link (which wins)', () => {
    expect(loadCharacterFilter(store(null), '', known)).toBe('all');
    expect(loadCharacterFilter(store('reginald'), '', known)).toBe('reginald');
    expect(loadCharacterFilter(store('reginald'), '?demo=1&c=biscuit', known)).toBe('biscuit');
    expect(loadCharacterFilter(store('reginald'), 'c=all', known)).toBe('all');
  });

  it('ignores a value that is not a character, in the link or in storage', () => {
    expect(loadCharacterFilter(store('nobody'), '', known)).toBe('all');
    expect(loadCharacterFilter(store('reginald'), '?c=nobody', known)).toBe('reginald');
    expect(parseCharacterFilter('outsider', known)).toBeNull();
    expect(parseCharacterFilter(5, known)).toBeNull();
    expect(loadCharacterFilter(store('biscuit'), '', [])).toBe('all'); // before the characters have loaded
  });

  it('works when storage is missing or throws (a private window, blocked site data)', () => {
    const throwing = { getItem: () => { throw new Error('SecurityError'); }, setItem: () => { throw new Error('QuotaExceededError'); } };
    expect(loadCharacterFilter(throwing, '', known)).toBe('all');
    expect(loadCharacterFilter(null, '', known)).toBe('all');
    expect(loadCharacterFilter(undefined, '?c=biscuit', known)).toBe('biscuit');
    expect(saveCharacterFilter(throwing, 'biscuit')).toBe(false);
    expect(saveCharacterFilter(null, 'biscuit')).toBe(false);
  });

  it('remembers the choice under one key', () => {
    const saved: Record<string, string> = {};
    expect(saveCharacterFilter({ setItem: (k, v) => void (saved[k] = v) }, 'reginald')).toBe(true);
    expect(saved).toEqual({ [CHARACTER_FILTER_KEY]: 'reginald' });
  });
});

describe('hash routes with a query', () => {
  it('reads #/more/scan?c=biscuit as the scan page with its query, and #/videos/<id> with its clip', () => {
    expect(parseHash('#/more/scan?c=biscuit')).toEqual({ route: 'more', param: 'scan', query: 'c=biscuit' });
    expect(parseHash('#/videos/abc-123')).toEqual({ route: 'videos', param: 'abc-123', query: '' });
    expect(parseHash('#/videos/abc-123?c=reginald')).toEqual({ route: 'videos', param: 'abc-123', query: 'c=reginald' });
    // terminal v2 (owner 2026-10-07): the app opens on Today; an unknown address falls back to it
    expect(parseHash('')).toEqual({ route: 'today', param: null, query: '' });
    expect(parseHash('#/nonsense?c=x').route).toBe('today');
    expect(parseHash('#/today')).toEqual({ route: 'today', param: null, query: '' });
  });

  it('builds the link the Characters page uses for “all picks of this character”', () => {
    expect(href('more', 'scan', { c: 'biscuit' })).toBe('#/more/scan?c=biscuit');
    expect(href('more', 'scan')).toBe('#/more/scan');
    expect(href('videos', 'abc')).toBe('#/videos/abc');
    expect(href('today')).toBe('#/');
    expect(href('clips')).toBe('#/clips');
  });
});

// ---- the demo shows both groups and every tier ----------------------------------------------------------------------------------------------------

describe('the demo data', () => {
  const NOW_MS = Date.parse('2026-10-06T12:00:00Z');
  const fresh = async () => new DemoBackend(() => NOW_MS).load();

  it('has picks for both characters and the unassigned group, in every tier, with a picture on most and a placeholder on some', async () => {
    const snap = await fresh();
    const sections = groupPicksByCharacter(snap.picks, snap.characters, { now: NOW_MS });
    expect(sections.map((s) => s.slug)).toEqual(['franz', 'reginald', 'lenny', 'biscuit', null]);
    for (const s of sections) expect([s.slug, s.slug === 'franz' || s.slug === 'lenny' ? s.picks.length === 0 : s.picks.length > 1]).toEqual([s.slug, true]);
    const tiers = new Set(snap.picks.map((p) => tierOf(p, NOW_MS).tier));
    expect([...tiers].sort()).toEqual([...TIERS].sort() as Tier[]);
    for (const slug of ['biscuit', 'reginald']) {
      expect(new Set(sections.find((s) => s.slug === slug)!.tiers.map((g) => g.tier)).size).toBeGreaterThanOrEqual(2);
    }
    expect(snap.picks.some((p) => p.platform === 'higgsfield' && thumbFor(p).original === null)).toBe(true); // a pure gallery pick
    const kinds = snap.picks.map((p) => thumbFor(p).kind);
    expect(kinds).toContain('image');
    expect(kinds).toContain('placeholder');
    expect(snap.picks.some((p) => thumbFor(p).aspect === '16:9')).toBe(true); // a YouTube card, letterboxed
    // real viral clips come first, the Genjutsu gallery is the backup, last in each section
    for (const s of sections.filter((x) => x.slug)) {
      const last = s.picks.map((p) => tierOf(p, NOW_MS).tier);
      expect(last.indexOf('gallery')).toBeGreaterThan(Math.max(...last.map((t, i) => (t === 'gallery' ? -1 : i))));
    }
  });

  it('carries every field of the analyst’s data on some pick, and none of it on others', async () => {
    const snap = await fresh();
    const facts = snap.picks.map((p) => ({ p, f: pickFacts(p, NOW_MS) }));
    expect(facts.some(({ f }) => f.posted && f.velocity && f.engagement && f.shares && f.saturation && f.matches.length > 0 && f.why && f.check)).toBe(true);
    expect(facts.some(({ p }) => p.velocity != null) && facts.some(({ p }) => p.velocity == null)).toBe(true);
    expect(facts.some(({ f }) => f.engagement && !f.shares)).toBe(true); // vidIQ gave no share count: no share rate invented
    expect(facts.some(({ p }) => p.saturation_count === 0) && facts.some(({ p }) => (p.saturation_count ?? 0) >= 8)).toBe(true);
    expect(facts.some(({ f }) => f.check?.some((c) => c.tone === 'bad'))).toBe(true); // a clip with a watermark
    expect(facts.some(({ f }) => f.check?.some((c) => c.tone === 'warn'))).toBe(true); // a handheld camera
    expect(facts.some(({ f }) => !f.why && !f.check && f.matches.length === 0)).toBe(true); // an unanalysed pick still renders
  });

  it('carries a theme on the scanned picks and gadgets on a proposed one', async () => {
    const snap = await fresh();
    expect(snap.picks.filter((p) => p.character_slug).every((p) => p.theme)).toBe(true);
    const withProps = snap.history.filter((h) => (h.owner_props ?? []).length > 0);
    expect(withProps.length).toBeGreaterThan(0);
    const proposed = pipelineFor('biscuit', snap, NOW_MS).proposed.items;
    expect(proposed.some((i) => i.ownerProps.length > 0)).toBe(true);
    expect(proposed.every((i) => TIERS.includes(i.tier) && i.tierLabel === TIER_LABELS[i.tier] && i.thumb)).toBe(true);
  });

  it('hands the Traits card of each character through the setup', async () => {
    const snap = await fresh();
    for (const c of snap.characters) expect(traitRows(c.setup.traits).length).toBe(8);
  });

  it('decidePick stores the gadgets and music like the RPC, and refuses what it refuses', async () => {
    const demo = new DemoBackend(() => NOW_MS);
    const [a, b, c, d] = (await demo.load()).picks.filter((p) => p.character_slug === 'reginald');
    await demo.decidePick(a.id, 'approve', null, null, { ownerProps: ['feather duster', 'handbell'], ownerMusic: 'in_app', ownerMode: 'dropin' });
    await expect(demo.decidePick(b.id, 'approve', null, null, { ownerProps: ['a', 'b', 'c', 'd'] })).rejects.toThrow(/at most 3/);
    await expect(demo.decidePick(b.id, 'approve', null, null, { ownerProps: ['x'.repeat(41)] })).rejects.toThrow(/1 to 40/);
    await expect(demo.decidePick(b.id, 'approve', null, null, { ownerMusic: 'spotify' as never })).rejects.toThrow(/owner_music/);
    await expect(demo.decidePick(b.id, 'approve', null, null, { ownerMode: 'recreate', ownerMusic: 'original' })).rejects.toThrow(/original needs the dropin mode/);
    await demo.decidePick(c.id, 'approve', null, null, { ownerMode: 'recreate', ownerMusic: 'ai_beat' });
    await demo.decidePick(d.id, 'skip', 'seen it', null, { ownerProps: ['x'], ownerMusic: 'in_app' });
    const rows = (await demo.load()).history;
    const row = (id: string) => rows.find((r) => r.id === id)!;
    expect([row(a.id).owner_props, row(a.id).owner_music]).toEqual([['feather duster', 'handbell'], 'in_app']);
    expect([row(c.id).owner_props, row(c.id).owner_music]).toEqual([null, 'ai_beat']);
    expect([row(d.id).status, row(d.id).owner_props, row(d.id).owner_music]).toEqual(['skipped', null, null]); // a skip stores nothing
    expect((await demo.load()).picks.some((p) => p.id === b.id)).toBe(true); // refused: still waiting
  });

  it('Both hands the sibling the same gadgets and music', async () => {
    const demo = new DemoBackend(() => NOW_MS);
    const p = (await demo.load()).picks.find((x) => x.character_slug === 'biscuit')!;
    await demo.decidePick(p.id, 'approve', null, 'biscuit', { alsoCharacter: 'reginald', ownerProps: ['gold chain'], ownerMusic: 'ai_beat' });
    const rows = (await demo.load()).history.filter((h) => h.url === p.url);
    expect(rows).toHaveLength(2);
    expect(rows.every((r) => r.owner_props?.[0] === 'gold chain' && r.owner_music === 'ai_beat')).toBe(true);
  });

  it('attachClip records the path the RPC would, with progress, and refuses a non-video', async () => {
    const demo = new DemoBackend(() => NOW_MS);
    const p = (await demo.load()).picks.find((x) => x.character_slug === 'reginald')!;
    const seen: number[] = [];
    const path = await demo.attachClip(p.id, { name: 'screen recording.mov', size: 9e6, type: 'video/quicktime' }, (n) => seen.push(n));
    expect(path).toBe(`owner/${p.id}/${NOW_MS}.mov`);
    expect(seen.at(-1)).toBe(100);
    expect(seen).toEqual([...seen].sort((x, y) => x - y)); // progress only goes up
    expect((await demo.load()).picks.find((x) => x.id === p.id)!.owner_clip_path).toBe(path);
    await expect(demo.attachClip(p.id, { name: 'notes.txt', size: 5, type: 'text/plain' })).rejects.toThrow(/not a video/);
    await expect(demo.attachClip('nope', { name: 'a.mp4', size: 5, type: 'video/mp4' })).rejects.toThrow(/unknown pick/);
  });
});

describe('the tab bar (terminal v2, owner 2026-10-07: five sections in the order of the work)', () => {
  it('opens on Today, ends with More, and keeps every page', async () => {
    const { TABS } = await import('./tabs');
    const { ROUTES, HOME } = await import('./hooks');
    expect(HOME).toBe('today');
    expect(TABS[0]).toEqual({ route: 'today', label: 'Today' });
    expect(TABS[TABS.length - 1]).toEqual({ route: 'more', label: 'More' });
    expect(TABS.filter((t) => 'later' in t)).toEqual([]); // the viral scan's "later" mark moved into More
    // nothing removed: the Scan page (Long list), Budget and every page stay; the artist page (#/artist/<slug>) is the one route without a tab
    expect(new Set(TABS.map((t) => t.route))).toEqual(new Set(ROUTES.filter((r) => r !== 'artist')));
    expect(TABS.map((t) => t.label)).toEqual(['Today', 'Clips', 'Videos', 'Characters', 'More']);
  });
});
