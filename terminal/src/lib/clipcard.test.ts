// Clip cards you can see and watch (terminal v3 Task 11, owner 2026-10-08: "make them larger so I can actually see them, maybe
// it's cards. Even better if I could click and watch them"): what a card shows, what its play button plays, and the demo.
import { readFileSync } from 'node:fs';
import { describe, expect, it } from 'vitest';
import { DemoBackend } from '../demo/backend';
import {
  MAKE_TOGGLE, afterPictureError, cardPrice, isOwnerMediaPath, mediaFragment, originalLink, pictureSources, playableFor, removeStep,
  sectionNote, shouldLoopBack, withFragment,
} from './clipcard';
import type { DropCard } from './types';

const PICK = '3f2a1c4e-0b5d-4e6f-8a9b-0c1d2e3f4a5b';
const READY: DropCard = {
  state: 'ready', kind: 'file', window: { start_s: 1.5, length_s: 9 }, credits: 102, seconds: 9,
  preview_path: `owner/${PICK}/preview.jpg`, cover_path: `owner/${PICK}/cover.jpg`, preview_video_path: `owner/${PICK}/preview.mp4`,
};
const TIKTOK = 'https://www.tiktok.com/@dancer.one/video/7688386199270001953';

describe('what a clip card plays (playableFor)', () => {
  it('1. plays the watch copy of the section the check wrote, whole (it is the section)', () => {
    expect(playableFor({ url: TIKTOK, platform: 'tiktok', owner_clip_path: `owner/${PICK}/1759700000000.mp4`, drop_card: READY })).toEqual({
      kind: 'file', path: `owner/${PICK}/preview.mp4`, from: 'preview', start: 0, end: null, note: null,
    });
  });

  it('2. else the owner’s own upload, from the start to the end of the section (his Adjust first)', () => {
    const card: DropCard = { ...READY, preview_video_path: null };
    const upload = `owner/${PICK}/1759700000000.mp4`;
    expect(playableFor({ url: `owner-drop:${PICK}`, platform: 'drop', owner_clip_path: upload, drop_card: card })).toEqual({
      kind: 'file', path: upload, from: 'upload', start: 1.5, end: 10.5, note: null,
    });
    expect(playableFor({ owner_clip_path: upload, drop_card: { ...card, adjust: { start_s: 3, length_s: 8 } } })).toMatchObject({ start: 3, end: 11 });
    // not checked yet: no section, the whole upload
    expect(playableFor({ owner_clip_path: upload, drop_card: { state: 'checking' } })).toMatchObject({ kind: 'file', start: 0, end: null });
  });

  it('3. else the original post opens on its platform in a new tab ("Watch on TikTok ↗"); a hit has no file and always does', () => {
    expect(playableFor({ url: TIKTOK, platform: 'tiktok', drop_card: { state: 'checking', kind: 'link' } })).toEqual({
      kind: 'link', url: TIKTOK, platform: 'tiktok', label: 'Watch on TikTok ↗',
    });
    expect(playableFor({ url: 'https://www.instagram.com/reel/DPabc123xyz/', platform: 'instagram' })).toMatchObject({ kind: 'link', label: 'Watch on Instagram ↗' });
    expect(playableFor({ url: 'https://www.youtube.com/shorts/abcdefghijk', platform: 'youtube' })).toMatchObject({ kind: 'link', label: 'Watch on YouTube ↗' });
  });

  it('4. else nothing: no play button (the card still shows)', () => {
    expect(playableFor({ url: `owner-drop:${PICK}`, platform: 'drop', owner_clip_path: null, drop_card: { state: 'uploading' } })).toEqual({ kind: 'none' });
    expect(playableFor({ url: 'http://www.tiktok.com/@a/video/1', platform: 'tiktok' })).toEqual({ kind: 'none' }); // never plain http
    expect(playableFor({ url: 'https://evil.example/www.tiktok.com/video', platform: 'tiktok' })).toEqual({ kind: 'none' });
    expect(playableFor({})).toEqual({ kind: 'none' });
  });

  it('only plays files the owner’s browser may read (sources/owner/<pick>/<file>, policy 0008)', () => {
    const card: DropCard = { ...READY, preview_video_path: 'clips/reginald/master.mp4' };
    expect(playableFor({ drop_card: card })).toEqual({ kind: 'none' });
    expect(playableFor({ owner_clip_path: '../owner/x.mp4', drop_card: { ...READY, preview_video_path: null } })).toEqual({ kind: 'none' });
    expect(isOwnerMediaPath(`owner/${PICK}/preview.mp4`)).toBe(true);
    expect(isOwnerMediaPath(`owner/${PICK}/cover.jpg`)).toBe(true);
    expect(isOwnerMediaPath(`owner/${PICK}/a/b.mp4`)).toBe(false);
    expect(isOwnerMediaPath(`owner/${PICK}/..`)).toBe(false);
    expect(isOwnerMediaPath(`owner/${PICK}/.`)).toBe(false);
    expect(isOwnerMediaPath(`owner/${PICK}/%2e%2e`)).toBe(false);
    expect(isOwnerMediaPath(`owner/${PICK}/%2E%2E%2Fx.mp4`)).toBe(false);
    expect(isOwnerMediaPath(`owner/${PICK}/.hidden.mp4`)).toBe(false);
    expect(isOwnerMediaPath(`owner/${PICK}/my clip.mp4`)).toBe(false);
    expect(isOwnerMediaPath(`owner/${PICK}/1759700000000.mp4`)).toBe(true);
    expect(isOwnerMediaPath(`owner/${PICK}/preview_2-b.v2.mp4`)).toBe(true);
    expect(isOwnerMediaPath('owner/p1/preview.mp4')).toBe(false);
    expect(isOwnerMediaPath(null)).toBe(false);
  });

  it('the live backend signs the same paths (its regex is this one)', () => {
    const src = readFileSync(new URL('./supabase.ts', import.meta.url), 'utf8');
    expect(src).toMatch(/async previewUrl\(path: string\) \{[\s\S]*?if \(!isOwnerMediaPath\(path\)\) return null;/);
  });
});

describe('when the owner’s Adjust moved the section (the video must be the section that will be made)', () => {
  const upload = `owner/${PICK}/1759700000000.mp4`;
  const moved: DropCard = { ...READY, adjust: { start_s: 4, length_s: 8 } }; // the check chose 1.5–10.5 s; Make it will use 4–12 s

  it('plays his own file at the effective section when it exists (it wins over the watch copy)', () => {
    expect(playableFor({ owner_clip_path: upload, drop_card: moved })).toEqual({
      kind: 'file', path: upload, from: 'upload', start: 4, end: 12, note: null,
    });
    // only a new length is enough, and only a new start too
    expect(playableFor({ owner_clip_path: upload, drop_card: { ...READY, adjust: { length_s: 7 } } })).toMatchObject({ from: 'upload', start: 1.5, end: 8.5 });
    expect(playableFor({ owner_clip_path: upload, drop_card: { ...READY, adjust: { start_s: 2 } } })).toMatchObject({ from: 'upload', start: 2, end: 11 });
  });

  it('else plays the watch copy and says in one muted line which section it shows and which is his', () => {
    const p = playableFor({ url: TIKTOK, platform: 'tiktok', drop_card: moved });
    expect(p).toEqual({
      kind: 'file', path: `owner/${PICK}/preview.mp4`, from: 'preview', start: 0, end: null,
      note: 'This shows the section the check chose (1.5–10.5 s); yours is 4–12 s.',
    });
    expect(sectionNote({ start: 1.5, length: 9 }, { start: 4, length: 8 })).toBe(p.kind === 'file' ? p.note : '');
  });

  it('does not say it when his Adjust left the section as the check chose it (other fields, or the same numbers)', () => {
    for (const adjust of [{ hook: 'a new hook' }, { star: 'the man in the waistcoat' }, { start_s: 1.5, length_s: 9 }, { start_s: 1.52 }, {}]) {
      expect(playableFor({ owner_clip_path: upload, drop_card: { ...READY, adjust } })).toMatchObject({ from: 'preview', note: null });
    }
  });

  it('a hit or a clip not checked yet has no section to differ from', () => {
    expect(playableFor({ owner_clip_path: upload, drop_card: { state: 'checking', adjust: { start_s: 3, length_s: 8 } } })).toMatchObject({ from: 'upload', note: null });
    expect(playableFor({ url: TIKTOK })).toMatchObject({ kind: 'link' });
  });
});

describe('the section in the player', () => {
  it('is a media fragment on the signed URL, and loops back to its start at its end', () => {
    expect(mediaFragment(1.5, 10.5)).toBe('#t=1.5,10.5');
    expect(mediaFragment(0, null)).toBe('');
    expect(mediaFragment(2.125, null)).toBe('#t=2.125');
    expect(withFragment('https://x.supabase.co/storage/v1/object/sign/sources/owner/a.mp4?token=abc', 1.5, 10.5)).toBe(
      'https://x.supabase.co/storage/v1/object/sign/sources/owner/a.mp4?token=abc#t=1.5,10.5',
    );
    expect(withFragment('https://x/a.mp4#t=9', 0, null)).toBe('https://x/a.mp4');
    expect(shouldLoopBack(10.46, 1.5, 10.5)).toBe(true);
    expect(shouldLoopBack(6, 1.5, 10.5)).toBe(false);
    expect(shouldLoopBack(1.2, 1.5, 10.5)).toBe(false);
    expect(shouldLoopBack(99, 0, null)).toBe(false); // the watch copy loops by itself
  });
});

describe('the card’s picture and lines', () => {
  it('shows the cover, else the strip’s middle frame, else the pick’s own tile', () => {
    expect(pictureSources(READY)).toEqual([{ kind: 'cover', path: READY.cover_path }, { kind: 'strip', path: READY.preview_path }]);
    expect(pictureSources({ ...READY, cover_path: null })).toEqual([{ kind: 'strip', path: READY.preview_path }]);
    expect(pictureSources({ state: 'checking' })).toEqual([]);
    expect(pictureSources(null)).toEqual([]);
    expect(pictureSources({ ...READY, cover_path: 'https://cdn.example/x.jpg' })).toEqual([{ kind: 'strip', path: READY.preview_path }]);
  });

  it('says the price and the length of the section in a few words', () => {
    expect(cardPrice(102, 9)).toBe('about 102 credits · 9 s');
    expect(cardPrice(97, 8.5)).toBe('about 97 credits · 8.5 s');
    expect(cardPrice(null, 9)).toBe('priced by the check');
  });

  it('has one Make toggle with two plain states', () => {
    expect(MAKE_TOGGLE.off).toEqual({ mark: '＋', text: 'Make this' });
    expect(MAKE_TOGGLE.on).toEqual({ mark: '✓', text: 'In your list' });
  });

  it('opens only https links on the three platforms', () => {
    expect(originalLink(TIKTOK)).toEqual({ url: TIKTOK, platform: 'tiktok' });
    expect(originalLink('https://m.tiktok.com/v/1.html')).toMatchObject({ platform: 'tiktok' });
    expect(originalLink('https://youtu.be/abcdefghijk')).toMatchObject({ platform: 'youtube' });
    expect(originalLink('owner-drop:abc')).toBeNull();
    expect(originalLink('javascript:alert(1)')).toBeNull();
    expect(originalLink('https://tiktok.com.evil.example/x')).toBeNull();
  });
});

describe('a picture that fails to load', () => {
  it('is signed once more (a URL may have expired), then gives way to the next file', () => {
    const first = afterPictureError({ step: 0, resigned: false });
    expect(first).toEqual({ step: 0, resigned: true });
    expect(afterPictureError(first)).toEqual({ step: 1, resigned: false });
    expect(afterPictureError({ step: 1, resigned: false })).toEqual({ step: 1, resigned: true });
  });
});

describe('Remove a clip, in two steps', () => {
  it('the first tap only asks, only the second removes', () => {
    const asked = removeStep('idle', 'ask');
    expect(asked).toEqual({ step: 'asking', remove: false });
    expect(removeStep(asked.step, 'confirm')).toEqual({ step: 'idle', remove: true });
  });

  it('"Keep it" goes back without removing, and a confirm nobody asked for removes nothing', () => {
    expect(removeStep('asking', 'cancel')).toEqual({ step: 'idle', remove: false });
    expect(removeStep('idle', 'cancel')).toEqual({ step: 'idle', remove: false });
    expect(removeStep('idle', 'confirm')).toEqual({ step: 'asking', remove: false });
  });
});

describe('the demo shows covers and the "no preview yet" state (no media files in git)', () => {
  it('gives its ready drops a cover and a watch copy; the cover is a picture, the video is not there', async () => {
    const demo = new DemoBackend(() => Date.parse('2026-10-08T12:00:00Z'));
    const ready = (await demo.load()).tracker.filter((r) => r.drop_card?.state === 'ready');
    expect(ready.length).toBeGreaterThan(3);
    for (const r of ready) {
      expect(r.drop_card?.cover_path).toBe(`owner/${r.pick_id}/cover.jpg`);
      expect(r.drop_card?.preview_video_path).toBe(`owner/${r.pick_id}/preview.mp4`);
      expect(playableFor(r)).toMatchObject({ kind: 'file', from: 'preview' });
    }
    const one = ready[0].drop_card!;
    expect((await demo.previewUrl(one.cover_path!))?.startsWith('data:image/svg+xml')).toBe(true);
    expect(await demo.previewUrl(one.preview_video_path!)).toBeNull();
    expect((await demo.previewUrl(one.preview_path!))?.startsWith('data:image/svg+xml')).toBe(true); // the strip as before
  });
});
