// Reads a character's folder (characters/<slug>/refs.json, bible.md, social.md) into the artist card the terminal's artist page
// shows (src/generated/artists.json, written by build-artists.mjs). Pure functions on strings, no file access, so vitest can drive
// them (src/lib/artist.test.ts). The bible is the source: its sections are found by their "## " heading (the start of it, any case),
// so "## Signature move (locked by the owner 2026-10-06)" is the "Signature move" section. A section a bible lacks is empty, never
// an error: a new character (the Borat-type, once named) shows what his folder has, with no code change.

/** The text under the first `## <heading...>` (to the next `## `), trimmed; "" when the bible has none. */
export function section(markdown, heading) {
  const out = [];
  let inside = false;
  for (const line of String(markdown ?? '').split('\n')) {
    if (line.startsWith('## ')) {
      if (inside) break;
      inside = line.slice(3).trim().toLowerCase().startsWith(heading.toLowerCase());
      continue;
    }
    if (inside) out.push(line);
  }
  return out.join('\n').trim();
}

const ITEM = /^(\s*)(?:[-*]|\d+\.)\s+(.*)$/;

/**
 * The list of a section: top-level `- ` / `1. ` items, each with its nested items as `children` and its continuation lines
 * joined on. Text that is not inside a list is skipped.
 */
export function listItems(text) {
  const items = [];
  let current = null;
  let child = null;
  for (const raw of String(text ?? '').split('\n')) {
    const m = ITEM.exec(raw);
    if (m) {
      const nested = m[1].length >= 2;
      if (nested && current) {
        child = { text: m[2].trim() };
        (current.children ??= []).push(child);
      } else {
        current = { text: m[2].trim() };
        child = null;
        items.push(current);
      }
      continue;
    }
    if (!raw.trim()) {
      current = null;
      child = null;
      continue;
    }
    if (current && /^\s+\S/.test(raw)) (child ?? current).text += ` ${raw.trim()}`;
    else current = null;
  }
  return items;
}

/** The first paragraph of a section that is not a list item (lines up to a blank line or a list), or null. */
export function firstParagraph(text) {
  const lines = [];
  for (const raw of String(text ?? '').split('\n')) {
    if (ITEM.test(raw) || !raw.trim()) {
      if (lines.length) break;
      continue;
    }
    lines.push(raw.trim());
  }
  return lines.length ? lines.join(' ') : null;
}

/**
 * The blocks of a section that starts each block with a bold lead line (`**Signature outfit (...):**`): `[{label, lead, items}]`,
 * `label` the bold text without its colon, `lead` the rest of that line, `items` its list.
 */
export function blocks(text) {
  const out = [];
  let cur = null;
  for (const raw of String(text ?? '').split('\n')) {
    const m = /^\*\*([^*]+?):?\*\*:?\s*(.*)$/.exec(raw);
    if (m && !ITEM.test(raw)) {
      cur = { label: m[1].replace(/:$/, '').trim(), lead: m[2].trim(), body: [] };
      out.push(cur);
    } else if (cur) cur.body.push(raw);
  }
  return out.map((b) => ({ label: b.label, lead: b.lead, items: listItems(b.body.join('\n')) }));
}

const clean = (s) => String(s ?? '').replace(/\*\*/g, '').replace(/`/g, '').trim();

/** The first markdown table of a section as rows keyed by the (cleaned) header cells. */
export function table(text) {
  const rows = String(text ?? '')
    .split('\n')
    .filter((l) => l.trim().startsWith('|'))
    .map((l) => l.trim().replace(/^\||\|$/g, '').split('|').map((c) => c.trim()));
  if (rows.length < 2) return [];
  const head = rows[0].map(clean);
  return rows
    .slice(1)
    .filter((r) => !r.every((c) => /^:?-{3,}:?$/.test(c)))
    .map((r) => Object.fromEntries(head.map((h, i) => [h, r[i] ?? ''])));
}

/** The bold quoted line of a section (`**"As you were."**` -> `As you were.`), or null. */
export function boldQuote(text) {
  const m = /\*\*["“]([^"”*]+)["”]\*\*/.exec(String(text ?? ''));
  return m ? m[1].trim() : null;
}

/** The caption title's edition word (`<famous moment or format> · agent edition` -> `agent`), or null. */
export function edition(voice) {
  const m = /· ([A-Za-z][A-Za-z -]{0,30}?) edition/.exec(String(voice ?? ''));
  return m ? m[1].trim() : null;
}

/** The Higgsfield voice of "How he talks": the preset's name, its voice id and a sample file name, each or null. */
export function voiceOf(text) {
  const t = String(text ?? '');
  const preset = /preset \*\*([A-Z][\w-]*)\*\*/.exec(t);
  const id = /voice_id ([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})/.exec(t);
  const file = /(hf_\d{8}_\d{6}_[0-9a-f-]{36}\.(?:wav|mp3|m4a))/.exec(t);
  return { preset: preset ? preset[1] : null, voice_id: id ? id[1] : null, sample_file: file ? file[1] : null };
}

/** The folder of the public Higgsfield CDN URLs (refs.json reference_urls), else the bible's "CDN prefix `https://...`". */
export function cdnPrefix(refs, bible) {
  const first = Object.values(refs?.reference_urls ?? {}).find((u) => typeof u === 'string' && u.startsWith('https://'));
  if (first) return first.slice(0, first.lastIndexOf('/') + 1);
  const m = /CDN prefix `(https:\/\/[^`]+\/)`/.exec(String(bible ?? ''));
  return m ? m[1] : null;
}

/** The first handle a social kit plans (`## Handles` -> its first `` `handle` ``), or null. */
export function plannedHandle(social) {
  const m = /`([a-z0-9._]+)`/i.exec(section(social, 'Handles'));
  return m ? m[1] : null;
}

const PLATFORMS = ['instagram', 'tiktok'];

/**
 * The artist card of one character: refs.json for the name, status, images, swap rule and accounts; the bible for everything
 * a person reads; social.md for a planned handle. `files` says which local copies exist (`spec`, `turnaround`, `avatar`):
 * their public paths are `/artists/<slug>/<file>`.
 */
export function parseArtist(refs, bible = '', social = '', files = {}) {
  const slug = refs.slug;
  const local = (name, file) => (files[name] ? `/artists/${slug}/${file}` : null);
  const body = (refs.bodies ?? [])[0] ?? 'biped';
  const urls = refs.reference_urls ?? {};
  const prefix = cdnPrefix(refs, bible);
  const concept = /^\*\*Concept:\*\*\s*(.+)$/m.exec(bible);

  const wardrobe = blocks(section(bible, 'Wardrobe'));
  const block = (start) => wardrobe.find((b) => b.label.toLowerCase().startsWith(start));
  const notPasteReady = (i) => !/^\*\*Paste-ready line/i.test(i.text);

  const move = section(bible, 'Signature move');
  const catchphrase = section(bible, 'Catchphrase');
  const talks = section(bible, 'How he talks');
  const voice = voiceOf(talks);
  const gadgetRows = table(section(bible, 'Gadgets ready'));
  const pick = (row, ...names) => {
    const key = Object.keys(row).find((k) => names.some((n) => k.toLowerCase() === n));
    return key ? clean(row[key]) || null : null;
  };
  const gadgets = gadgetRows.length
    ? gadgetRows.map((r) => ({ name: pick(r, 'gadget') ?? '', status: pick(r, 'status'), job: pick(r, 'viral job', 'job') })).filter((g) => g.name)
    : (refs.traits?.props ?? []).map((p) => (typeof p === 'string' ? { name: p, status: null, job: null } : { name: p.name, status: null, job: p.job ?? null }));

  const planned = plannedHandle(social);
  const accounts = PLATFORMS.map((platform) => {
    const a = (refs.accounts ?? []).find((x) => x.platform === platform);
    const plan = a?.planned_handle ?? (planned ? (platform === 'tiktok' ? `@${planned}` : planned) : null);
    return { platform, handle: a?.handle ?? null, planned: plan, connected: Boolean(a?.postiz_integration_id) };
  });

  return {
    slug,
    name: refs.name ?? slug,
    status: refs.status ?? 'designing',
    concept: concept ? concept[1].trim() : null,
    edition: edition(section(bible, 'Voice (captions)')),
    images: {
      spec: local('spec', 'spec.png'),
      turnaround: local('turnaround', 'turnaround.jpg'),
      avatar: local('avatar', 'avatar.png'),
      turnaround_url: urls[`sheet_${body}`] ?? null,
      master_url: urls[`master_${body}`] ?? null,
    },
    look: listItems(section(bible, 'Look lock')),
    wardrobe: {
      signature: (block('signature outfit')?.items ?? []).filter(notPasteReady),
      capsule: block('capsule')?.items ?? [],
    },
    motion: listItems(section(bible, 'Motion')).filter((i) => !/^\*\*Signature move:\*\*/i.test(i.text)),
    signature_move: { text: firstParagraph(move), notes: listItems(move) },
    catchphrase: { line: boldQuote(catchphrase), text: firstParagraph(catchphrase), notes: listItems(catchphrase) },
    voice: {
      preset: voice.preset,
      voice_id: voice.voice_id,
      sample_url: voice.sample_file && prefix ? `${prefix}${voice.sample_file}` : null,
      items: listItems(talks),
    },
    gadgets,
    swap: { text: firstParagraph(section(bible, 'Swap rule')), noun: refs.swap?.noun ?? null, stars: refs.swap?.stars ?? [] },
    accounts,
  };
}
