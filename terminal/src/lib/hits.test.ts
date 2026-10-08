// Terminal v3, the cloud hits job in the terminal (spec section 10): "Hot right now" (the general lane, top 10) and each
// character's "Worth saving" (his top 5 new hits), the plain lines on a hit card, who may take a general hit, and "Use this clip"
// (add_drop of the link, then the hit marked dropped). Pure helpers, plus the demo backend's v_hits, set_hit_status and
// set_drop_keep; no browser.
import { describe, expect, it } from 'vitest';
import {
  HIT_DAYS, KEEP_HINT, fileHit, hitNumbers, hitTakers, hitTitle, hitWhy, hotNow, keepable, laneOf, offeredHits, postLink, postedLabel, reachLabel,
  worthSaving,
} from './hits';
import type { Backend, Character, DropCard, DropState, Hit, TrackerRow } from './types';

const NOW = Date.parse('2026-10-08T12:00:00Z');
const HOUR = 3_600_000;
const DAY = 24 * HOUR;
const ago = (ms: number) => new Date(NOW - ms).toISOString();

let n = 0;
const hit = (over: Partial<Hit> = {}): Hit => {
  n += 1;
  return {
    hit_id: `hit-${String(n).padStart(3, '0')}`, platform: 'tiktok', url: `https://www.tiktok.com/@dancer${n}/video/76883861992700${String(n).padStart(5, '0')}`,
    creator_handle: `@dancer${n}`, followers: 10_000, views: 120_000, likes: 9_000, comments: 300, shares: 200, saves: 150,
    posted_at: ago(2 * DAY), caption: `a dance ${n}`, sound: 'original sound', duration_s: 14, thumbnail_url: null, keyword: 'dance trend',
    character_slug: 'reginald', character_name: 'Reginald', reach: 12, score: 50, first_seen: ago(DAY), last_seen: ago(HOUR),
    ...over,
  };
};
const ids = (hs: ReadonlyArray<Hit>) => hs.map((h) => h.hit_id);

const character = (slug: string, over: Partial<Character> = {}): Character => ({
  slug, name: { franz: 'Franz', reginald: 'Reginald', lenny: 'Lenny Gold', biscuit: 'Biscuit' }[slug] ?? slug, status: 'live',
  bodies: ['biped'], setup: { stars: ['person'] }, accounts: [], ...over,
});
const ROSTER: Character[] = [
  character('lenny'),
  character('biscuit', { status: 'paused', bodies: ['biped', 'quadruped'], setup: { stars: ['dog', 'animal'] } }),
  character('reginald'),
  character('franz', { bodies: ['biped', 'quadruped'], setup: { stars: ['dog', 'person'] } }),
];

describe('worthSaving: his top new hits', () => {
  it('keeps only his new hits, best score first, at most 5 by default', () => {
    const mine = [30, 90, 50, 70, 10, 60].map((score) => hit({ score }));
    const others = [hit({ score: 99, character_slug: 'franz', character_name: 'Franz' }), hit({ score: 98, character_slug: null, character_name: null })];
    const gone = [hit({ score: 95, status: 'dropped' }), hit({ score: 94, status: 'dismissed' })];
    const top = worthSaving([...others, ...gone, ...mine], 'reginald');
    expect(top.map((h) => h.score)).toEqual([90, 70, 60, 50, 30]);
    expect(top.every((h) => h.character_slug === 'reginald')).toBe(true);
    expect(worthSaving(mine, 'reginald', 2).map((h) => h.score)).toEqual([90, 70]);
    expect(worthSaving(mine, 'lenny')).toEqual([]);
    expect(worthSaving(mine, 'reginald', 0)).toEqual([]);
  });

  it('breaks a tie on the score by the latest seen, then by id, so the order never jumps', () => {
    const a = hit({ score: 80, last_seen: ago(5 * HOUR) });
    const b = hit({ score: 80, last_seen: ago(HOUR) });
    const c = hit({ score: 80, last_seen: ago(HOUR), hit_id: 'hit-000' });
    expect(ids(worthSaving([a, b, c], 'reginald'))).toEqual([c.hit_id, b.hit_id, a.hit_id]);
  });

  it('treats a row without a status as new (v_hits lists only new hits and has no status column)', () => {
    const h = hit({ score: 40 });
    delete (h as Partial<Hit>).status;
    expect(ids(worthSaving([h], 'reginald'))).toEqual([h.hit_id]);
  });
});

describe('hotNow: the general lane', () => {
  it('keeps only the general lane (no character), new only, best first, top 10 by default', () => {
    const general = Array.from({ length: 12 }, (_, i) => hit({ score: 10 + i * 5, character_slug: null, character_name: null }));
    const his = hit({ score: 100 });
    const dismissed = hit({ score: 99, character_slug: null, status: 'dismissed' });
    const hot = hotNow([his, dismissed, ...general]);
    expect(hot).toHaveLength(10);
    expect(hot[0].score).toBe(65);
    expect(hot.every((h) => h.character_slug == null)).toBe(true);
    expect(hotNow(general, 3).map((h) => h.score)).toEqual([65, 60, 55]);
    expect(laneOf(his)).toBe('reginald');
    expect(laneOf(general[0])).toBe('general');
  });
});

describe('offeredHits: what v_hits lists', () => {
  it('the new hits posted in the last 14 days or with no known date, best first', () => {
    const fresh = hit({ score: 40 });
    const undated = hit({ score: 60, posted_at: null });
    const old = hit({ score: 99, posted_at: ago((HIT_DAYS + 1) * DAY) });
    const edge = hit({ score: 50, posted_at: ago(HIT_DAYS * DAY - HOUR) });
    const dropped = hit({ score: 90, status: 'dropped' });
    expect(ids(offeredHits([fresh, undated, old, edge, dropped], NOW))).toEqual([undated.hit_id, edge.hit_id, fresh.hit_id]);
  });
});

describe('the lines on a hit card', () => {
  it('reach: views against the creator’s followers, rounded for a glance; nothing without it', () => {
    expect(reachLabel(12.3)).toBe('12× his followers');
    expect(reachLabel(2.46)).toBe('2.5× his followers');
    expect(reachLabel(3)).toBe('3× his followers');
    expect(reachLabel(0.42)).toBe('0.4× his followers');
    expect(reachLabel(0.01)).toBe('under 0.1× his followers');
    expect(reachLabel(1234)).toBe('1,234× his followers');
    expect(reachLabel(null)).toBeNull();
    expect(reachLabel(Number.NaN)).toBeNull();
    expect(reachLabel(Number.POSITIVE_INFINITY)).toBeNull();
  });

  it('posted: how long ago, in hours under a day, in days after', () => {
    expect(postedLabel(ago(2 * DAY + 3 * HOUR), NOW)).toBe('2 days ago');
    expect(postedLabel(ago(DAY), NOW)).toBe('1 day ago');
    expect(postedLabel(ago(5 * HOUR), NOW)).toBe('5 hours ago');
    expect(postedLabel(ago(HOUR + 60_000), NOW)).toBe('1 hour ago');
    expect(postedLabel(ago(10 * 60_000), NOW)).toBe('just now');
    expect(postedLabel(new Date(NOW + HOUR).toISOString(), NOW)).toBe('just now'); // a clock a little ahead
    expect(postedLabel(null, NOW)).toBe('posting date unknown');
    expect(postedLabel('not a date', NOW)).toBe('posting date unknown');
  });

  it('numbers: views (or likes when the platform gave no play count), reach, posted', () => {
    expect(hitNumbers(hit({ views: 1_234_567, reach: 12.3, posted_at: ago(2 * DAY) }), NOW)).toEqual(['1.2M views', '12× his followers', '2 days ago']);
    expect(hitNumbers(hit({ views: null, likes: 85_000, reach: null, posted_at: ago(5 * HOUR) }), NOW)).toEqual(['85K likes', '5 hours ago']);
    expect(hitNumbers(hit({ views: null, likes: null, reach: null, posted_at: null }), NOW)).toEqual(['posting date unknown']);
  });

  it('why: rising, spreading, brand new or big, then what it was found for', () => {
    expect(hitWhy(hit({ reach: 12, posted_at: ago(2 * DAY), keyword: 'dog dance' }), NOW)).toBe('Rising fast · found for “dog dance”');
    expect(hitWhy(hit({ reach: 5, posted_at: ago(9 * DAY), keyword: null }), NOW)).toBe('Spreading far past the creator’s fans · on the trending feed');
    expect(hitWhy(hit({ reach: 0.5, posted_at: ago(10 * HOUR), views: 50_000, keyword: 'office dance' }), NOW)).toBe('Brand new · found for “office dance”');
    expect(hitWhy(hit({ reach: null, posted_at: ago(6 * DAY), views: 2_000_000, keyword: null }), NOW)).toBe('Over a million views · on the trending feed');
    expect(hitWhy(hit({ reach: 0.5, posted_at: ago(6 * DAY), views: 50_000, keyword: 'butler' }), NOW)).toBe('Found for “butler”');
    expect(hitWhy(hit({ reach: null, posted_at: null, views: null, keyword: '  ' }), NOW)).toBe('On the trending feed');
  });

  it('title: the caption’s first line, else who posted it where', () => {
    expect(hitTitle(hit({ caption: '  POV: the boss walks in\nsecond line #fyp ' }))).toBe('POV: the boss walks in');
    expect(hitTitle(hit({ caption: null, creator_handle: '@dancer.one', platform: 'instagram' }))).toBe('@dancer.one on Instagram');
    expect(hitTitle(hit({ caption: '   ', creator_handle: null, platform: 'tiktok' }))).toBe('A TikTok video');
    expect(hitTitle(hit({ caption: 'x'.repeat(200) })).length).toBeLessThanOrEqual(120);
  });

  it('postLink: only an https link is ever opened', () => {
    expect(postLink('https://www.tiktok.com/@a/video/1')).toBe('https://www.tiktok.com/@a/video/1');
    expect(postLink('javascript:alert(1)')).toBeNull();
    expect(postLink('http://www.tiktok.com/@a/video/1')).toBeNull();
    expect(postLink('')).toBeNull();
    expect(postLink(null)).toBeNull();
  });

});

describe('keepable: where the Keep toggle shows', () => {
  const row = (state: DropState | null, over: Partial<Pick<TrackerRow, 'status' | 'make_requested_at'>> = {}) => ({
    drop_card: state ? ({ state } as DropCard) : null, status: 'approved', make_requested_at: null, ...over,
  });

  it('on a drop not made yet, the only clips retention may delete (studio.fetch.purge_stale)', () => {
    for (const s of ['uploading', 'checking', 'waiting', 'ready', 'blocked', 'failed'] as const) expect(keepable(row(s))).toBe(true);
    expect(keepable(row('ready', { status: 'analysed' }))).toBe(true);
    expect(KEEP_HINT).toBe('Kept clips are never deleted');
  });

  it('never on a clip being made or made, after Make it, on a pick queued or made, or on a row that is no drop', () => {
    expect(keepable(row('making'))).toBe(false);
    expect(keepable(row('made'))).toBe(false);
    expect(keepable(row('ready', { make_requested_at: ago(HOUR) }))).toBe(false);
    expect(keepable(row('ready', { status: 'queued' }))).toBe(false);
    expect(keepable(row('ready', { status: 'made' }))).toBe(false);
    expect(keepable(row(null))).toBe(false);
  });
});

describe('hitTakers: who may take a general hit', () => {
  it('every live character in the owner’s order when the hit names no kind of star', () => {
    expect(hitTakers(hit({ keyword: 'viral dance', character_slug: null }), ROSTER).map((c) => c.slug)).toEqual(['franz', 'reginald', 'lenny']);
    expect(hitTakers(hit({ keyword: null, character_slug: null }), ROSTER).map((c) => c.name)).toEqual(['Franz', 'Reginald', 'Lenny Gold']);
  });

  it('like for like when the hit says it is a dog (its keyword): only those who replace a dog and have the body for it', () => {
    expect(hitTakers(hit({ keyword: 'Dachshund', character_slug: null }), ROSTER).map((c) => c.slug)).toEqual(['franz']);
    expect(hitTakers(hit({ keyword: 'puppy trend', character_slug: null }), ROSTER).map((c) => c.slug)).toEqual(['franz']);
    // a character seeded before the stars list is judged by his body alone, as copy_drop does
    const old = [character('reginald', { setup: {} }), character('lenny', { setup: {}, bodies: ['biped', 'quadruped'] })];
    expect(hitTakers(hit({ keyword: 'dog dance', character_slug: null }), old).map((c) => c.slug)).toEqual(['lenny']);
    // "hotdog" is no dog
    expect(hitTakers(hit({ keyword: 'hotdog dance', character_slug: null }), ROSTER).map((c) => c.slug)).toEqual(['franz', 'reginald', 'lenny']);
  });

  it('nobody when no character is live', () => {
    expect(hitTakers(hit({ character_slug: null }), ROSTER.map((c) => ({ ...c, status: 'paused' })))).toEqual([]);
    expect(hitTakers(hit({ character_slug: null }), [character('lenny', { status: 'designing' })])).toEqual([]);
  });
});

describe('fileHit: "Use this clip"', () => {
  const fake = (over: Partial<Pick<Backend, 'addDrop' | 'setHitStatus'>> = {}) => {
    const calls: string[] = [];
    const backend: Pick<Backend, 'addDrop' | 'setHitStatus'> = {
      addDrop: async (slug, link) => {
        calls.push(`add_drop ${slug} ${link}`);
        return { pickId: 'pick-9', duplicate: false };
      },
      setHitStatus: async (id, status) => {
        calls.push(`set_hit_status ${id} ${status}`);
      },
      ...over,
    };
    return { backend, calls };
  };

  it('files the canonical link for that character, then marks the hit dropped', async () => {
    const { backend, calls } = fake();
    const h = hit({ hit_id: 'h1', url: 'https://tiktok.com/@Dancer.One/video/7688386199270001953?is_from_webapp=1' });
    const r = await fileHit(backend, h, 'franz');
    expect(calls).toEqual(['add_drop franz https://www.tiktok.com/@dancer.one/video/7688386199270001953', 'set_hit_status h1 dropped']);
    expect(r).toEqual({ pickId: 'pick-9', duplicate: false, marked: true, markError: null });
  });

  it('sends the stored link as it is when it is not one the terminal can tidy (the database judges it)', async () => {
    const { backend, calls } = fake();
    await fileHit(backend, hit({ hit_id: 'h2', url: 'https://example.com/v/1' }), 'lenny');
    expect(calls[0]).toBe('add_drop lenny https://example.com/v/1');
  });

  it('a refused add_drop marks nothing and says why', async () => {
    const { backend, calls } = fake({ addDrop: async () => { throw new Error('unknown character x'); } });
    await expect(fileHit(backend, hit({ hit_id: 'h3' }), 'x')).rejects.toThrow('unknown character x');
    expect(calls).toEqual([]);
  });

  it('a filed clip whose hit could not be marked says so instead of failing (the drop exists)', async () => {
    const { backend } = fake({ setHitStatus: async () => { throw new Error('only the owner may mark a hit'); } });
    const r = await fileHit(backend, hit({ hit_id: 'h4' }), 'reginald');
    expect(r).toEqual({ pickId: 'pick-9', duplicate: false, marked: false, markError: 'only the owner may mark a hit' });
  });
});

describe('the demo backend: v_hits, set_hit_status, set_drop_keep', () => {
  it('lists several new hits per live character and a general lane, best first, never one older than 14 days', async () => {
    const { DemoBackend } = await import('../demo/backend');
    const snap = await new DemoBackend(() => NOW).load();
    for (const slug of ['franz', 'reginald', 'lenny']) expect(worthSaving(snap.hits, slug).length).toBeGreaterThanOrEqual(3);
    expect(hotNow(snap.hits).length).toBeGreaterThanOrEqual(6);
    expect(snap.hits.every((h) => h.posted_at == null || NOW - Date.parse(h.posted_at) <= HIT_DAYS * DAY)).toBe(true);
    const scores = snap.hits.map((h) => h.score);
    expect(scores).toEqual([...scores].sort((a, b) => b - a));
    expect(snap.hits.some((h) => h.thumbnail_url == null)).toBe(true); // the placeholder is shown too
    expect(snap.hits.some((h) => h.views == null && h.likes != null)).toBe(true); // an Instagram search hit: likes only
  });

  it('keeps an old hit out of v_hits even with the best score', async () => {
    const { DemoBackend, DEMO_OLD_HIT_ID } = await import('../demo/backend');
    const demo = new DemoBackend(() => NOW);
    expect((await demo.load()).hits.some((h) => h.hit_id === DEMO_OLD_HIT_ID)).toBe(false);
  });

  it('Not for us hides a hit; Use this clip files it as his drop and hides it; refusals in plain words', async () => {
    const { DemoBackend } = await import('../demo/backend');
    const demo = new DemoBackend(() => NOW);
    let snap = await demo.load();
    const [first, second] = worthSaving(snap.hits, 'franz');
    await demo.setHitStatus(first.hit_id, 'dismissed');
    snap = await demo.load();
    expect(snap.hits.some((h) => h.hit_id === first.hit_id)).toBe(false);
    const r = await fileHit(demo, second, 'franz');
    expect(r.marked).toBe(true);
    snap = await demo.load();
    expect(snap.hits.some((h) => h.hit_id === second.hit_id)).toBe(false);
    const filed = snap.tracker.find((t) => t.pick_id === r.pickId)!;
    expect(filed.character_slug).toBe('franz');
    expect(filed.url).toBe(second.url);
    expect(filed.drop_card?.kind).toBe('link');
    await expect(demo.setHitStatus('nope', 'dismissed')).rejects.toThrow(/unknown hit/);
    await expect(demo.setHitStatus(second.hit_id, 'gone' as never)).rejects.toThrow(/new, dropped or dismissed/);
    await demo.setHitStatus(first.hit_id, 'new'); // back again
    expect((await demo.load()).hits.some((h) => h.hit_id === first.hit_id)).toBe(true);
  });

  it('Keep sets drop.keep on a drop and refuses a pick that is not one', async () => {
    const { DemoBackend } = await import('../demo/backend');
    const demo = new DemoBackend(() => NOW);
    const snap = await demo.load();
    const drop = snap.tracker.find((t) => t.drop_card && t.drop_card.keep !== true)!;
    await demo.setDropKeep(drop.pick_id, true);
    expect((await demo.load()).tracker.find((t) => t.pick_id === drop.pick_id)!.drop_card!.keep).toBe(true);
    await demo.setDropKeep(drop.pick_id, false);
    expect((await demo.load()).tracker.find((t) => t.pick_id === drop.pick_id)!.drop_card!.keep).toBe(false);
    const notDrop = snap.tracker.find((t) => !t.drop_card);
    if (notDrop) await expect(demo.setDropKeep(notDrop.pick_id, true)).rejects.toThrow(/not a dropped video/);
    await expect(demo.setDropKeep('nope', true)).rejects.toThrow(/unknown pick/);
    await expect(demo.setDropKeep(drop.pick_id, null as never)).rejects.toThrow(/true or false/);
  });
});
