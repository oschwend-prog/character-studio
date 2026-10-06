// "Make it": the sheet an Approve opens. Which character (or Both: one clip each), an optional note for the analyst, how to
// loop him in (and, for a Drop-in, how big his part is), his gadgets & jewellery, where the music comes from, an optional
// clip of your own, and what it will cost. Nothing blocks on a clip: without one a real video is made automatically as
// a Recreate, with one it is a true Drop-in.
import { ExternalLink, Paperclip } from 'lucide-react';
import { useId, useMemo, useState, type ChangeEvent, type FormEvent } from 'react';
import { platformName } from '../lib/format';
import {
  CLIP_HELP, CLIP_MAX_SECONDS, NOTE_MAX, PROPS_MAX, PROP_MAX_CHARS, defaultMusicForMode, gadgetList, hasUsableSource, makeItPayload,
  musicOptionsFor, sheetEstimate, traitProps, validateClipFile, type MakeItChoice,
} from '../lib/rules';
import { activeRoster } from '../lib/roster';
import { useStudio } from '../lib/store';
import type { OwnerMode, OwnerMusic, OwnerPresence, Pick } from '../lib/types';
import { PickThumb } from './PickThumb';
import { Sheet, Spinner } from './ui';

export const MODE_OPTIONS: { id: 'analyst' | OwnerMode; name: string; help: string }[] = [
  { id: 'analyst', name: 'Analyst decides', help: 'Claude picks the better of the two for this clip: a Drop-in when it has a clip to drive it, else a Recreate.' },
  {
    id: 'dropin',
    name: 'Drop-in',
    help: 'Put him into the original viral clip: a Genjutsu gallery clip, or the file you attach below. Without one it is made automatically as a Recreate.',
  },
  { id: 'recreate', name: 'Recreate', help: 'Re-make the moves with him, in a scene of his own.' },
];

export const PRESENCE_OPTIONS: { id: OwnerPresence; name: string; help: string }[] = [
  { id: 'cameo', name: 'Cameo', help: 'He is in the scene, small and natural: replaces a background element, little movement.' },
  { id: 'featured', name: 'Featured', help: 'He takes the main performer’s moves; the original scene stays the star.' },
  { id: 'star', name: 'Star', help: 'He IS the video: full-body performance, every beat is his, framing favours him.' },
];

type Attach =
  | { phase: 'idle' }
  | { phase: 'reading'; name: string }
  | { phase: 'uploading'; name: string; pct: number }
  | { phase: 'done'; name: string; path: string }
  | { phase: 'error'; message: string };

/** The length of a video the browser can read (null when it cannot): checked before anything is uploaded. */
function readDuration(file: File): Promise<number | null> {
  return new Promise((resolve) => {
    const url = URL.createObjectURL(file);
    const v = document.createElement('video');
    let timer = 0;
    const done = (d: number | null) => {
      window.clearTimeout(timer);
      URL.revokeObjectURL(url);
      v.removeAttribute('src');
      resolve(d);
    };
    timer = window.setTimeout(() => done(null), 10_000);
    v.preload = 'metadata';
    v.muted = true;
    v.onloadedmetadata = () => done(Number.isFinite(v.duration) ? v.duration : null);
    v.onerror = () => done(null);
    v.src = url;
  });
}

export function MakeItSheet({ pick, onClose }: { pick: Pick; onClose(): void }) {
  const { backend, data, run, busy } = useStudio();
  const ids = useId();
  const roster = useMemo(() => {
    // who a new video can be made with: not a paused (retired) character; the roster until the characters have loaded
    const list = activeRoster(data?.characters);
    return {
      slugs: list.map((c) => c.slug),
      names: Object.fromEntries(list.map((c) => [c.slug, c.name])) as Record<string, string>,
    };
  }, [data?.characters]);

  const [choice, setChoice] = useState<MakeItChoice>({
    character: pick.character_slug && roster.slugs.includes(pick.character_slug) ? pick.character_slug : null,
    note: '',
    mode: 'analyst',
    presence: 'featured',
    props: pick.owner_props ?? [],
    customProp: '',
  });
  const [music, setMusic] = useState<OwnerMusic | null>(pick.owner_music ?? null);
  const [attach, setAttach] = useState<Attach>({ phase: 'idle' });
  const [error, setError] = useState<string | null>(null);
  const key = `pick-${pick.id}`;
  const working = busy.has(key);
  const canBoth = roster.slugs.length === 2;
  const set = (patch: Partial<MakeItChoice>) => {
    setChoice((c) => ({ ...c, ...patch }));
    setError(null);
  };

  // the gadgets offered: the chosen character's traits props (both characters' for Both)
  const chips = useMemo(() => {
    const slugs = choice.character === 'both' ? roster.slugs : choice.character ? [choice.character] : [];
    const seen = new Map<string, string | null>();
    for (const slug of slugs) {
      for (const p of traitProps(data?.characters.find((c) => c.slug === slug)?.setup?.traits)) if (!seen.has(p.name)) seen.set(p.name, p.job);
    }
    return [...seen.entries()].map(([name, job]) => ({ name, job }));
  }, [choice.character, roster.slugs, data?.characters]);

  const attachedPath = attach.phase === 'done' ? attach.path : null;
  const usable = hasUsableSource({ gallery: pick.gallery, owner_clip_path: pick.owner_clip_path }, attachedPath);
  const options = musicOptionsFor(choice.mode);
  const effectiveMusic: OwnerMusic = music && options.some((o) => o.id === music) ? music : defaultMusicForMode(choice.mode);
  const estimate = sheetEstimate({ mode: choice.mode, music: effectiveMusic, clips: choice.character === 'both' ? 2 : 1, usableSource: usable });
  const gadgets = gadgetList(choice.props ?? [], choice.customProp ?? '');
  const gadgetCount = gadgets.ok ? gadgets.items.length : PROPS_MAX + 1;
  const canAttach = choice.mode !== 'recreate' && !pick.gallery;

  const toggleChip = (name: string) => {
    const has = (choice.props ?? []).includes(name);
    set({ props: has ? (choice.props ?? []).filter((p) => p !== name) : [...(choice.props ?? []), name] });
  };

  const onFile = async (e: ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    e.target.value = ''; // the same file can be chosen again
    if (!file) return;
    setAttach({ phase: 'reading', name: file.name });
    const checked = validateClipFile(file, await readDuration(file));
    if (!checked.ok) {
      setAttach({ phase: 'error', message: checked.reason });
      return;
    }
    setAttach({ phase: 'uploading', name: file.name, pct: 0 });
    try {
      const path = await backend.attachClip(pick.id, { name: file.name, size: file.size, type: file.type, blob: file }, (pct) =>
        setAttach({ phase: 'uploading', name: file.name, pct }),
      );
      setAttach({ phase: 'done', name: file.name, path });
    } catch (err) {
      setAttach({ phase: 'error', message: err instanceof Error ? err.message : String(err) });
    }
  };

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    const payload = makeItPayload({ ...choice, music: effectiveMusic }, {
      pickCharacter: pick.character_slug, characters: roster.slugs, names: roster.names, pick, attachedPath,
    });
    if (!payload.ok) {
      setError(payload.reason);
      return;
    }
    const ok = await run(key, () => backend.decidePick(pick.id, 'approve', null, payload.characterSlug, payload.extras), payload.summary);
    if (ok) onClose();
  };

  const noteLeft = NOTE_MAX - choice.note.length;
  const hook = pick.hook ? `“${pick.hook}”` : pick.creator_handle ?? pick.url;
  const uploading = attach.phase === 'uploading' || attach.phase === 'reading';
  return (
    <Sheet title="Make it" onClose={onClose}>
      <form className="sheet-body" onSubmit={submit} aria-describedby={`${ids}-what`}>
        <div className="sheet-what">
          <PickThumb pick={pick} size="small" />
          <p className="small muted" id={`${ids}-what`} style={{ margin: 0 }}>
            {hook} · {platformName(pick.platform)}
            {pick.creator_handle ? ` · ${pick.creator_handle}` : ''}{' '}
            {/^https:/.test(pick.url) && (
              <a href={pick.url} target="_blank" rel="noopener noreferrer" aria-label={`Open the original on ${platformName(pick.platform)} (new tab)`}>
                original <ExternalLink size={12} aria-hidden="true" />
              </a>
            )}
          </p>
        </div>

        <div className="field" role="group" aria-labelledby={`${ids}-char`}>
          <span className="label" id={`${ids}-char`}>Character</span>
          <div className="seg wide">
            {roster.slugs.map((slug) => (
              <button key={slug} type="button" className={slug} aria-pressed={choice.character === slug} onClick={() => set({ character: slug })}>
                {roster.names[slug]}
              </button>
            ))}
            {canBoth && (
              <button type="button" aria-pressed={choice.character === 'both'} onClick={() => set({ character: 'both' })}>
                Both
              </button>
            )}
          </div>
          <span className="hint">
            {choice.character === 'both' ? 'Both: one clip each, made from the same video.' : 'Pre-selected: the analyst’s pick.'}
          </span>
        </div>

        <div className="field">
          <label className="label" htmlFor={`${ids}-note`}>Note for the analyst (optional)</label>
          <textarea
            id={`${ids}-note`}
            className="textarea"
            value={choice.note}
            maxLength={NOTE_MAX}
            rows={3}
            placeholder="slow-mo on the drop"
            onChange={(e) => set({ note: e.target.value })}
            aria-describedby={`${ids}-count`}
          />
          <span className="hint num" id={`${ids}-count`} aria-live="polite">
            {noteLeft} characters left
          </span>
        </div>

        <fieldset className="options">
          <legend className="label">How to loop him in</legend>
          {MODE_OPTIONS.map((o) => (
            <label key={o.id} className="option" data-checked={choice.mode === o.id}>
              <input type="radio" name={`${ids}-mode`} value={o.id} checked={choice.mode === o.id} onChange={() => set({ mode: o.id })} />
              <span>
                <b>{o.name}</b>
                <span className="small muted">{o.help}</span>
              </span>
            </label>
          ))}
        </fieldset>

        {choice.mode === 'dropin' && (
          <fieldset className="options">
            <legend className="label">His part</legend>
            {PRESENCE_OPTIONS.map((o) => (
              <label key={o.id} className="option" data-checked={choice.presence === o.id}>
                <input type="radio" name={`${ids}-part`} value={o.id} checked={choice.presence === o.id} onChange={() => set({ presence: o.id })} />
                <span>
                  <b>{o.name}</b>
                  <span className="small muted">{o.help}</span>
                </span>
              </label>
            ))}
          </fieldset>
        )}

        {canAttach && (
          <div className="field attach" role="group" aria-labelledby={`${ids}-attach`}>
            <span className="label" id={`${ids}-attach`}>Your clip (optional)</span>
            <span className="hint">{CLIP_HELP}</span>
            <label className={`btn line attach-btn${uploading ? ' disabled' : ''}`}>
              <Paperclip aria-hidden="true" /> {attach.phase === 'done' || pick.owner_clip_path ? 'Replace clip' : 'Attach clip'}
              <input type="file" accept="video/*" className="sr-only" onChange={onFile} disabled={uploading} />
            </label>
            {attach.phase === 'reading' && <span className="small muted" role="status">Reading {attach.name}…</span>}
            {attach.phase === 'uploading' && (
              <span className="small" role="status">
                <progress max={100} value={attach.pct} aria-label="Upload progress" /> Uploading {attach.name}: {attach.pct}%
              </span>
            )}
            {attach.phase === 'done' && <span className="small ok-text" role="status">Attached: {attach.name}</span>}
            {attach.phase === 'idle' && pick.owner_clip_path && <span className="small ok-text">A clip is already attached to this pick.</span>}
            {attach.phase === 'error' && (
              <span className="error-text" role="alert">
                {attach.message}
              </span>
            )}
            <span className="hint">Up to {CLIP_MAX_SECONDS} s and 200 MB. It stays in your own storage and is only used to make this video.</span>
          </div>
        )}
        {pick.gallery && choice.mode !== 'recreate' && (
          <span className="hint">A Genjutsu gallery clip: it already has its driving video, nothing to attach.</span>
        )}
        {choice.mode !== 'recreate' && !usable && (
          <p className="notice" role="note" style={{ margin: 0 }}>
            {estimate.note}
          </p>
        )}

        <div className="field" role="group" aria-labelledby={`${ids}-props`}>
          <span className="label" id={`${ids}-props`}>
            Gadgets &amp; jewellery <span className="muted num">{Math.min(gadgetCount, PROPS_MAX)} of {PROPS_MAX}</span>
          </span>
          {chips.length > 0 && (
            <div className="chips gadget-chips">
              {chips.map((c) => {
                const on = (choice.props ?? []).includes(c.name);
                return (
                  <button
                    key={c.name} type="button" className="chip gadget" aria-pressed={on} title={c.job ?? undefined}
                    disabled={!on && gadgetCount >= PROPS_MAX} onClick={() => toggleChip(c.name)}
                  >
                    <span>{c.name}</span>
                    {c.job && <span className="chip-hint">{c.job}</span>}
                  </button>
                );
              })}
            </div>
          )}
          <label className="sr-only" htmlFor={`${ids}-custom`}>Your own gadget</label>
          <input
            id={`${ids}-custom`} className="input" value={choice.customProp ?? ''} maxLength={PROP_MAX_CHARS}
            placeholder="Or your own: tiny gold chain, aviator shades" onChange={(e) => set({ customProp: e.target.value })}
          />
          <span className="hint">Worn or held, never a brand logo. Up to {PROPS_MAX}, {PROP_MAX_CHARS} characters each.</span>
        </div>

        <fieldset className="options">
          <legend className="label">Music</legend>
          {options.map((o) => (
            <label key={o.id} className="option" data-checked={effectiveMusic === o.id}>
              <input type="radio" name={`${ids}-music`} value={o.id} checked={effectiveMusic === o.id} onChange={() => setMusic(o.id)} />
              <span>
                <b>{o.name}</b>
                <span className="small muted">{o.help}</span>
                {o.note && <span className="small note-grey">{o.note}</span>}
              </span>
            </label>
          ))}
        </fieldset>

        <p className="estimate" aria-live="polite">
          <b className="num">{estimate.label}</b>
          <span className="small muted">{estimate.effective === 'dropin' ? 'Drop-in' : 'Recreate'}{choice.character === 'both' ? ', one clip each' : ''}</span>
        </p>

        {error && (
          <span className="error-text" role="alert">
            {error}
          </span>
        )}
        <div className="sheet-actions">
          <button type="button" className="btn ghost" onClick={onClose}>
            Cancel
          </button>
          <button type="submit" className="btn primary" disabled={!choice.character || working || uploading || !gadgets.ok} aria-busy={working}>
            {working && <Spinner />} Make it
          </button>
        </div>
      </form>
    </Sheet>
  );
}
