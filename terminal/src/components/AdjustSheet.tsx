// "Adjust" on a ready drop: who is replaced, his part, his gadgets, the hook, the section (start and length) and, for a
// landscape clip, where the 9:16 crop sits. The price follows the section live. Its button is Make it with these settings:
// only what the owner changed is sent (request_job checks it, and the CLI checks it again before anything is spent).
import { useId, useMemo, useState, type FormEvent } from 'react';
import {
  DROP_MAX_SECONDS, DROP_MIN_SECONDS, PART_LABEL, adjustChanges, dropCredits, effectiveDrop, isLandscape, sectionLabel, validateAdjust,
} from '../lib/drop';
import { PROPS_MAX, PROP_MAX_CHARS, traitProps } from '../lib/rules';
import { useStudio } from '../lib/store';
import type { DropAdjust, OwnerPresence, TrackerRow } from '../lib/types';
import { PRESENCE_OPTIONS } from './MakeIt';
import { Sheet, Spinner } from './ui';

export function AdjustSheet({
  row, onClose, onMake, working,
}: { row: TrackerRow; onClose(): void; onMake(adjust: DropAdjust): void; working: boolean }) {
  const { data } = useStudio();
  const ids = useId();
  const d = row.drop_card!;
  const start = effectiveDrop(d, d.adjust ?? {});
  const [star, setStar] = useState(start.star);
  const [part, setPart] = useState<OwnerPresence>(start.part);
  const [gadgets, setGadgets] = useState<string[]>(start.gadgets);
  const [custom, setCustom] = useState('');
  const [hook, setHook] = useState(start.hook);
  const [from, setFrom] = useState(String(start.start_s));
  const [length, setLength] = useState(String(start.length_s));
  const [crop, setCrop] = useState(start.crop_x ?? 0.5);
  const [error, setError] = useState<string | null>(null);

  const chips = useMemo(
    () => traitProps(data?.characters.find((c) => c.slug === row.character_slug)?.setup?.traits).map((p) => p),
    [data?.characters, row.character_slug],
  );
  const landscape = isLandscape(d);
  const all = [...gadgets, ...(custom.trim() ? [custom.trim()] : [])];
  const wanted = {
    star, part, gadgets: all, hook, start_s: Number(from), length_s: Number(length), crop_x: landscape ? crop : null,
  };
  const changes = adjustChanges(d, wanted);
  const checked = validateAdjust(changes, d);
  const credits = dropCredits(d, checked.ok ? changes : {});

  const toggle = (name: string) =>
    setGadgets((g) => (g.includes(name) ? g.filter((x) => x !== name) : g.length + (custom.trim() ? 1 : 0) >= PROPS_MAX ? g : [...g, name]));

  const submit = (e: FormEvent) => {
    e.preventDefault();
    if (!checked.ok) {
      setError(checked.reason);
      return;
    }
    onMake(changes);
  };

  return (
    <Sheet title="Adjust" onClose={onClose}>
      <form className="sheet-body" onSubmit={submit}>
        <div className="field">
          <label className="label" htmlFor={`${ids}-star`}>Who is replaced</label>
          <input id={`${ids}-star`} className="input" value={star} maxLength={80} onChange={(e) => { setStar(e.target.value); setError(null); }} />
          <span className="hint">By position or clothes: “the man in the grey suit in the middle”.</span>
        </div>

        <fieldset className="options">
          <legend className="label">His part</legend>
          {PRESENCE_OPTIONS.map((o) => (
            <label key={o.id} className="option" data-checked={part === o.id}>
              <input type="radio" name={`${ids}-part`} value={o.id} checked={part === o.id} onChange={() => setPart(o.id)} />
              <span>
                <b>{PART_LABEL[o.id]}</b>
                <span className="small muted">{o.help}</span>
              </span>
            </label>
          ))}
        </fieldset>

        <div className="field" role="group" aria-labelledby={`${ids}-props`}>
          <span className="label" id={`${ids}-props`}>
            Gadgets &amp; jewellery <span className="muted num">{Math.min(all.length, PROPS_MAX)} of {PROPS_MAX}</span>
          </span>
          {chips.length > 0 && (
            <div className="chips gadget-chips">
              {chips.map((c) => {
                const on = gadgets.includes(c.name);
                return (
                  <button key={c.name} type="button" className="chip gadget" aria-pressed={on} title={c.job ?? undefined}
                    disabled={!on && all.length >= PROPS_MAX} onClick={() => toggle(c.name)}>
                    <span>{c.name}</span>
                    {c.job && <span className="chip-hint">{c.job}</span>}
                  </button>
                );
              })}
            </div>
          )}
          <label className="sr-only" htmlFor={`${ids}-custom`}>Your own gadget</label>
          <input id={`${ids}-custom`} className="input" value={custom} maxLength={PROP_MAX_CHARS} placeholder="Or your own: tiny gold chain"
            onChange={(e) => setCustom(e.target.value)} />
        </div>

        <fieldset className="options">
          <legend className="label">The hook on screen</legend>
          {(d.hooks ?? []).filter(Boolean).map((h) => (
            <label key={h} className="option" data-checked={hook === h}>
              <input type="radio" name={`${ids}-hook`} value={h} checked={hook === h} onChange={() => setHook(h)} />
              <span><b>“{h}”</b></span>
            </label>
          ))}
          <label className="sr-only" htmlFor={`${ids}-hook-own`}>Your own hook</label>
          <input id={`${ids}-hook-own`} className="input" value={hook} maxLength={80} onChange={(e) => { setHook(e.target.value); setError(null); }} />
        </fieldset>

        <div className="field" role="group" aria-labelledby={`${ids}-section`}>
          <span className="label" id={`${ids}-section`}>Section</span>
          <div className="drop-section">
            <label>
              <span className="small muted">Starts at (s)</span>
              <input className="input num" type="number" inputMode="decimal" min={0} step={0.5} value={from}
                onChange={(e) => { setFrom(e.target.value); setError(null); }} />
            </label>
            <label>
              <span className="small muted">Lasts (s)</span>
              <input className="input num" type="number" inputMode="decimal" min={DROP_MIN_SECONDS} max={DROP_MAX_SECONDS} step={0.5} value={length}
                onChange={(e) => { setLength(e.target.value); setError(null); }} />
            </label>
          </div>
          <span className="hint num">
            {checked.ok ? sectionLabel(Number(from), Number(length)) : checked.reason}
            {d.duration_s ? ` · the video is ${Number(d.duration_s.toFixed(1))} s` : ''} · a classic 12-15 s, other clips 8-10 s
          </span>
        </div>

        {landscape && (
          <div className="field">
            <label className="label" htmlFor={`${ids}-crop`}>Crop to 9:16 around the star</label>
            <input id={`${ids}-crop`} type="range" min={0} max={1} step={0.01} value={crop} onChange={(e) => setCrop(Number(e.target.value))}
              aria-valuetext={`${Math.round(crop * 100)}% from the left`} />
            <span className="hint num">{Math.round(crop * 100)}% from the left edge</span>
          </div>
        )}

        <p className="estimate" aria-live="polite">
          <b className="num">about {credits} credits</b>
          <span className="small muted">Genjutsu is paid per second of the section</span>
        </p>
        {error && <span className="error-text" role="alert">{error}</span>}
        <div className="sheet-actions">
          <button type="button" className="btn ghost" onClick={onClose}>Cancel</button>
          <button type="submit" className="btn primary" disabled={working || !checked.ok} aria-busy={working}>
            {working && <Spinner />} Make it
          </button>
        </div>
      </form>
    </Sheet>
  );
}
