// Terminal v3, the cloud hits job in the terminal (spec section 10): "Hot right now" (the general lane, top 10) and each
// character's "Worth saving" (his top 5 new hits), the plain lines on a hit card, who may take a general hit, and "Use this clip"
// (add_drop of the link, then the hit marked dropped). Pure helpers, plus the demo backend's v_hits, set_hit_status and
// set_drop_keep; no browser.
import { describe, expect, it } from 'vitest';
import {
  HIT_DAYS, HOT_LIMIT, WORTH_LIMIT, fileHit, filedLine, hitFromRow, hitLaneSlugs, hitNumbers, hitTakers, hitTitle, hitWhy, hitsByLane,
  hotNow, keepHint, keepable, laneOf, mergeHitLanes, offeredHits, postLink, postedLabel, reachLabel, worthSaving, type FiledHit,
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
    expect(reachLabel(12.3)).toBe('12× the creator’s followers');
    expect(reachLabel(2.46)).toBe('2.5× the creator’s followers');
    expect(reachLabel(3)).toBe('3× the creator’s followers');
    expect(reachLabel(0.42)).toBe('0.4× the creator’s followers');
    expect(reachLabel(0.01)).toBe('under 0.1× the creator’s followers');
    expect(reachLabel(1234)).toBe('1,234× the creator’s followers');
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
    expect(hitNumbers(hit({ views: 1_234_567, reach: 12.3, posted_at: ago(2 * DAY) }), NOW)).toEqual(['1.2M views', '12× the creator’s followers', '2 days ago']);
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
  });

  it('says what Keep does, and what happens without it', () => {
    expect(keepHint(true)).toBe('Kept: never deleted for going unused');
    expect(keepHint(false)).toBe('Unused clips are deleted after 30 days (60 for your own)');
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
  it('every live character in the owner’s order, whatever the hit (the card offers “Let the check choose” before them)', () => {
    expect(hitTakers(ROSTER).map((c) => c.slug)).toEqual(['franz', 'reginald', 'lenny']);
    expect(hitTakers(ROSTER).map((c) => c.name)).toEqual(['Franz', 'Reginald', 'Lenny Gold']);
  });

  it('nobody paused or designing', () => {
    expect(hitTakers(ROSTER.map((c) => ({ ...c, status: 'paused' })))).toEqual([]);
    expect(hitTakers([character('lenny', { status: 'designing' })])).toEqual([]);
  });
});

describe('loading v_hits per lane', () => {
  it('asks one lane per live character, in the owner’s order', () => {
    expect(hitLaneSlugs(ROSTER)).toEqual(['franz', 'reginald', 'lenny']);
    expect(hitLaneSlugs([character('lenny', { status: 'designing' }), ...ROSTER.filter((c) => c.slug !== 'lenny')])).toEqual(['franz', 'reginald']);
  });

  it('reads a row with numbers as strings (PostgREST bigint) and a missing number as null, never 0', () => {
    const h = hitFromRow({ ...hit(), views: '1200000', followers: '9000', reach: '133.3', likes: null, score: '87', duration_s: '' });
    expect([h.views, h.followers, h.reach, h.likes, h.score, h.duration_s]).toEqual([1_200_000, 9000, 133.3, null, 87, null]);
    expect(hitFromRow({ ...hit(), score: null }).score).toBe(0);
  });

  it('merges the lanes, each hit once, best first', () => {
    const a = hit({ score: 50, character_slug: null });
    const b = hit({ score: 90 });
    const c = hit({ score: 70, character_slug: 'franz' });
    expect(ids(mergeHitLanes([[a], [b, a], [c]]))).toEqual([b.hit_id, c.hit_id, a.hit_id]);
    expect(mergeHitLanes([])).toEqual([]);
  });

  it('keeps the general lane’s top 10 and each live character’s top 5, so a busy lane never crowds out another', () => {
    const general = Array.from({ length: 14 }, (_, i) => hit({ score: 99 - i, character_slug: null }));
    const franz = Array.from({ length: 7 }, (_, i) => hit({ score: 40 - i, character_slug: 'franz' }));
    const lenny = [hit({ score: 5, character_slug: 'lenny' })];
    const paused = [hit({ score: 98, character_slug: 'biscuit' })];
    const kept = hitsByLane([...general, ...franz, ...lenny, ...paused], ['franz', 'reginald', 'lenny']);
    expect(kept.filter((h) => h.character_slug == null)).toHaveLength(HOT_LIMIT);
    expect(kept.filter((h) => h.character_slug === 'franz').map((h) => h.score)).toEqual([40, 39, 38, 37, 36]);
    expect(kept.filter((h) => h.character_slug === 'franz')).toHaveLength(WORTH_LIMIT);
    expect(kept.some((h) => h.character_slug === 'lenny')).toBe(true);
    expect(kept.some((h) => h.character_slug === 'biscuit')).toBe(false);
  });
});

describe('fileHit: "Use this clip"', () => {
  type Fake = Pick<Backend, 'addDrop' | 'setHitStatus' | 'requestJob'>;
  const fake = (over: Partial<Fake> = {}) => {
    const calls: string[] = [];
    const backend: Fake = {
      addDrop: async (slug, link) => {
        calls.push(`add_drop ${slug} ${link}`);
        return { pickId: 'pick-9', duplicate: false, status: 'approved', characterSlug: slug ?? 'reginald' };
      },
      setHitStatus: async (id, status) => {
        calls.push(`set_hit_status ${id} ${status}`);
      },
      requestJob: async (pickId, kind) => {
        calls.push(`request_job ${pickId} ${kind}`);
        return { dispatched: true };
      },
      ...over,
    };
    return { backend, calls };
  };
  const base: FiledHit = {
    pickId: 'pick-9', duplicate: false, onItsWay: false, characterSlug: 'franz', marked: true, markError: null, check: 'now', checkError: null,
  };

  it('files the canonical link for that character, marks the hit dropped, then starts the free check (as the Add clips box does)', async () => {
    const { backend, calls } = fake();
    const h = hit({ hit_id: 'h1', url: 'https://tiktok.com/@Dancer.One/video/7688386199270001953?is_from_webapp=1' });
    const r = await fileHit(backend, h, 'franz');
    expect(calls).toEqual([
      'add_drop franz https://www.tiktok.com/@dancer.one/video/7688386199270001953', 'set_hit_status h1 dropped', 'request_job pick-9 process',
    ]);
    expect(r).toEqual(base);
  });

  it('with no character the free check chooses (add_drop without one: character_by studio)', async () => {
    const { backend, calls } = fake();
    const r = await fileHit(backend, hit({ hit_id: 'h5' }), null);
    expect(calls[0]).toMatch(/^add_drop null https:\/\/www\.tiktok\.com\//);
    expect(r.characterSlug).toBe('reginald'); // the provisional character it waits under
  });

  it('sends the stored link as it is when it is not one the terminal can tidy (the database judges it)', async () => {
    const { backend, calls } = fake();
    await fileHit(backend, hit({ hit_id: 'h2', url: 'https://example.com/v/1' }), 'lenny');
    expect(calls[0]).toBe('add_drop lenny https://example.com/v/1');
  });

  it('a refused add_drop marks nothing, checks nothing and says why', async () => {
    const { backend, calls } = fake({ addDrop: async () => { throw new Error('unknown character x'); } });
    await expect(fileHit(backend, hit({ hit_id: 'h3' }), 'x')).rejects.toThrow('unknown character x');
    expect(calls).toEqual([]);
  });

  it('a filed clip whose hit could not be marked says so instead of failing, and is still checked', async () => {
    const { backend, calls } = fake({ setHitStatus: async () => { throw new Error('only the owner may mark a hit'); } });
    const r = await fileHit(backend, hit({ hit_id: 'h4' }), 'franz');
    expect(r).toEqual({ ...base, marked: false, markError: 'only the owner may mark a hit' });
    expect(calls.at(-1)).toBe('request_job pick-9 process');
  });

  it('a refused check request keeps the drop (the sweep checks it within 2 hours) and says why', async () => {
    const { backend } = fake({ requestJob: async () => { throw new Error('the dispatch failed'); } });
    const r = await fileHit(backend, hit({ hit_id: 'h6' }), 'franz');
    expect(r).toEqual({ ...base, check: 'soon', checkError: 'the dispatch failed' });
    const { backend: quiet } = fake({ requestJob: async () => ({ dispatched: false }) });
    expect((await fileHit(quiet, hit({ hit_id: 'h7' }), 'franz')).check).toBe('soon');
  });

  it('a duplicate: the check request’s refusal is ignored; a pick being made or made is not asked to check again', async () => {
    const { backend } = fake({
      addDrop: async () => ({ pickId: 'pick-9', duplicate: true, status: 'approved', characterSlug: 'franz' }),
      requestJob: async () => { throw new Error('a check runs on an uploading, checking, waiting or failed drop'); },
    });
    expect(await fileHit(backend, hit({ hit_id: 'h8' }), 'franz')).toEqual({ ...base, duplicate: true, check: 'soon' });
    const made = fake({ addDrop: async () => ({ pickId: 'pick-9', duplicate: true, status: 'made', characterSlug: 'franz' }) });
    const r = await fileHit(made.backend, hit({ hit_id: 'h9' }), 'franz');
    expect(r).toEqual({ ...base, duplicate: true, onItsWay: true, check: 'none' });
    expect(made.calls).toEqual(['set_hit_status h9 dropped']);
  });
});

describe('filedLine: the line after "Use this clip", true to what happened', () => {
  const base: FiledHit = {
    pickId: 'p', duplicate: false, onItsWay: false, characterSlug: 'franz', marked: true, markError: null, check: 'now', checkError: null,
  };
  const names = (s: string) => ({ franz: 'Franz', reginald: 'Reginald' })[s] ?? s;

  it('a new drop: checked now, or within 2 hours', () => {
    expect(filedLine(base, 'Franz')).toEqual({ text: 'Filed for Franz: being checked now (free)', kind: 'ok' });
    expect(filedLine({ ...base, check: 'soon', checkError: 'x' }, 'Franz').text).toBe('Filed for Franz: it is checked within 2 hours (free)');
    expect(filedLine({ ...base, characterSlug: 'reginald' }, null, names).text).toBe('Filed: the free check chooses who goes in (checking now)');
  });

  it('a duplicate: already in his clips, checked again, or being made or made', () => {
    expect(filedLine({ ...base, duplicate: true }, 'Franz').text).toBe('Already in Franz’s clips: checked again now (free)');
    expect(filedLine({ ...base, duplicate: true, onItsWay: true, check: 'none' }, 'Franz').text).toBe('Already in Franz’s clips (being made or made)');
    expect(filedLine({ ...base, duplicate: true, onItsWay: true, check: 'none', characterSlug: 'reginald' }, null, names).text)
      .toBe('Already in Reginald’s clips (being made or made)');
  });

  it('a refused mark is said, as an error', () => {
    expect(filedLine({ ...base, marked: false, markError: 'only the owner may mark a hit' }, 'Franz')).toEqual({
      text: 'Filed for Franz: being checked now (free). The hit is still listed as new: only the owner may mark a hit', kind: 'error',
    });
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

  it('a link filed alone is not checked until it is asked (as live); Use this clip asks, and the check ends ready', async () => {
    const { DemoBackend } = await import('../demo/backend');
    let now = NOW;
    const demo = new DemoBackend(() => now);
    const [h] = hotNow((await demo.load()).hits);
    const alone = await demo.addDrop('lenny', 'https://www.tiktok.com/@someone.else/video/7699999999999999999');
    const r = await fileHit(demo, h, null); // "Let the check choose"
    now += 2_500;
    const snap = await demo.load();
    expect(snap.tracker.find((t) => t.pick_id === alone.pickId)!.drop_card?.state).toBe('checking'); // nobody asked
    const checked = snap.tracker.find((t) => t.pick_id === r.pickId)!;
    expect(checked.drop_card?.state === 'ready' || checked.drop_card?.state === 'blocked').toBe(true);
    expect(checked.drop_card?.character_by).toBe('studio');
    // the same hit again: already in his clips, the check's refusal ignored
    const again = await fileHit(demo, h, null);
    expect(again.duplicate).toBe(true);
    expect(again.checkError).toBeNull();
  });

  it('shows at most the general lane’s top 10 and each live character’s top 5', async () => {
    const { DemoBackend } = await import('../demo/backend');
    const snap = await new DemoBackend(() => NOW).load();
    expect(snap.hits.filter((h) => h.character_slug == null).length).toBeLessThanOrEqual(HOT_LIMIT);
    for (const slug of ['franz', 'reginald', 'lenny']) expect(snap.hits.filter((h) => h.character_slug === slug).length).toBeLessThanOrEqual(WORTH_LIMIT);
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
    expect(r).toMatchObject({ marked: true, check: 'now', duplicate: false, characterSlug: 'franz' });
    snap = await demo.load();
    expect(snap.hits.some((h) => h.hit_id === second.hit_id)).toBe(false);
    const filed = snap.tracker.find((t) => t.pick_id === r.pickId)!;
    expect(filed.character_slug).toBe('franz');
    expect(filed.url).toBe(second.url);
    expect(filed.drop_card?.kind).toBe('link');
    expect(filed.drop_card?.state).toBe('checking');
    expect(filed.drop_card?.requested?.process).toBe(new Date(NOW).toISOString()); // the check was asked for, as live
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
