// "Make it": the sheet an Approve opens. Which character (or Both: one clip each), an optional note for the
// analyst, how to loop him in (and, for a Drop-in, how big his part is). Nothing else: no energy, no prop.
import { ExternalLink } from 'lucide-react';
import { useId, useMemo, useState, type FormEvent } from 'react';
import { platformName } from '../lib/format';
import { NOTE_MAX, makeItPayload, type MakeItChoice } from '../lib/rules';
import { useStudio } from '../lib/store';
import type { OwnerMode, OwnerPresence, Pick } from '../lib/types';
import { Sheet, Spinner } from './ui';

export const MODE_OPTIONS: { id: 'analyst' | OwnerMode; name: string; help: string }[] = [
  { id: 'analyst', name: 'Analyst decides', help: 'Claude picks the better of the two for this clip.' },
  {
    id: 'dropin',
    name: 'Drop-in',
    help: 'Put him into the original viral clip. Needs a clean copy of it (no watermark, overlays or other people) in your inbox; without one he is made as Recreate.',
  },
  { id: 'recreate', name: 'Recreate', help: 'Re-make the moves with him, in a scene of his own.' },
];

export const PRESENCE_OPTIONS: { id: OwnerPresence; name: string; help: string }[] = [
  { id: 'cameo', name: 'Cameo', help: 'He is in the scene, small and natural: replaces a background element, little movement.' },
  { id: 'featured', name: 'Featured', help: 'He takes the main performer’s moves; the original scene stays the star.' },
  { id: 'star', name: 'Star', help: 'He IS the video: full-body performance, every beat is his, framing favours him.' },
];

/** The fallback when the studio has not loaded its characters (the two launch characters). */
const LAUNCH = ['biscuit', 'reginald'];

export function MakeItSheet({ pick, onClose }: { pick: Pick; onClose(): void }) {
  const { backend, data, run, busy } = useStudio();
  const ids = useId();
  const roster = useMemo(() => {
    const list = data?.characters.length ? data.characters : LAUNCH.map((slug) => ({ slug, name: slug.charAt(0).toUpperCase() + slug.slice(1) }));
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
  });
  const [error, setError] = useState<string | null>(null);
  const key = `pick-${pick.id}`;
  const working = busy.has(key);
  const canBoth = roster.slugs.length === 2;
  const set = (patch: Partial<MakeItChoice>) => {
    setChoice((c) => ({ ...c, ...patch }));
    setError(null);
  };

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    const payload = makeItPayload(choice, { pickCharacter: pick.character_slug, characters: roster.slugs, names: roster.names });
    if (!payload.ok) {
      setError(payload.reason);
      return;
    }
    const ok = await run(key, () => backend.decidePick(pick.id, 'approve', null, payload.characterSlug, payload.extras), payload.summary);
    if (ok) onClose();
  };

  const noteLeft = NOTE_MAX - choice.note.length;
  const hook = pick.hook ? `“${pick.hook}”` : pick.creator_handle ?? pick.url;
  return (
    <Sheet title="Make it" onClose={onClose}>
      <form className="sheet-body" onSubmit={submit} aria-describedby={`${ids}-what`}>
        <p className="small muted" id={`${ids}-what`} style={{ margin: 0 }}>
          {hook} · {platformName(pick.platform)}
          {pick.creator_handle ? ` · ${pick.creator_handle}` : ''}{' '}
          <a href={pick.url} target="_blank" rel="noopener noreferrer" aria-label={`Open the original on ${platformName(pick.platform)} (new tab)`}>
            original <ExternalLink size={12} aria-hidden="true" />
          </a>
        </p>

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

        {error && (
          <span className="error-text" role="alert">
            {error}
          </span>
        )}
        <div className="sheet-actions">
          <button type="button" className="btn ghost" onClick={onClose}>
            Cancel
          </button>
          <button type="submit" className="btn primary" disabled={!choice.character || working} aria-busy={working}>
            {working && <Spinner />} Make it
          </button>
        </div>
      </form>
    </Sheet>
  );
}
