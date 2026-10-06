// One dropped video before its clip is on the 8-step stepper: Uploading → Checking → Ready ("about N credits", a preview
// strip, who gets replaced, the section, the hook) with Make it and a small Adjust; or why it waits, cannot be used, or
// failed. Make it is the owner's approval of this one video: nothing is generated before it (request_job, migration 0012).
import { AlertTriangle, SlidersHorizontal } from 'lucide-react';
import { useEffect, useState } from 'react';
import { DROP_STATE_LABEL, PART_LABEL, dropActions, dropCredits, dropLine, dropTitle, effectiveDrop, sectionLabel } from '../lib/drop';
import { useStudio } from '../lib/store';
import type { DropAdjust, TrackerRow } from '../lib/types';
import { AdjustSheet } from './AdjustSheet';
import { Livery, Spinner } from './ui';

export function DropCard({ row, now }: { row: TrackerRow; now: number }) {
  const { backend, run, busy } = useStudio();
  const d = row.drop_card!;
  const [adjusting, setAdjusting] = useState(false);
  const [strip, setStrip] = useState<string | null>(null);
  const key = `drop-${row.pick_id}`;
  const working = busy.has(key);
  const title = dropTitle(row);
  const titleId = `drop-${row.pick_id}`;
  const actions = dropActions(d, now);
  const flagged = d.state === 'blocked' || d.state === 'failed' || d.state === 'waiting' || (d.state === 'uploading' && actions.includes('remove'));
  const e = effectiveDrop(d, d.adjust ?? {});

  useEffect(() => {
    let live = true;
    setStrip(null);
    if (d.preview_path) void backend.previewUrl(d.preview_path).then((u) => live && setStrip(u));
    return () => {
      live = false;
    };
  }, [backend, d.preview_path]);

  const make = (adjust: DropAdjust | null) =>
    run(key, () => backend.requestJob(row.pick_id, 'make', adjust), `Make it: ${row.character_name ?? 'he'} is on his way (about ${dropCredits(d, adjust ?? {})} credits)`);
  const recheck = () => run(key, () => backend.requestJob(row.pick_id, 'process'), 'Checking it again');
  const remove = () => run(key, () => backend.decidePick(row.pick_id, 'skip', 'removed by the owner from In the works', null), 'Removed');

  return (
    <article className="panel pick work drop-card" data-char={row.character_slug ?? 'none'} data-drop={d.state} aria-labelledby={titleId}>
      <div className="pick-badges">
        <span className={`drop-state ${d.state}`}>{DROP_STATE_LABEL[d.state]}</span>
        {row.character_slug && <Livery slug={row.character_slug} />}
        {d.kind === 'link' && <span className="small muted">{row.creator_handle ?? 'a link'}</span>}
      </div>
      <h3 className="work-title" id={titleId}>{title}</h3>

      {d.state === 'ready' || strip ? (
        <div className="drop-strip">
          {strip ? (
            <img src={strip} alt={`Five frames of the section ${e.start_s}-${e.start_s + e.length_s} s`} loading="lazy" decoding="async" />
          ) : (
            <span className="drop-strip-empty small muted">No preview</span>
          )}
        </div>
      ) : null}

      {d.state === 'ready' ? (
        <dl className="drop-facts">
          <div><dt>Replaces</dt><dd>{e.star}</dd></div>
          <div><dt>His part</dt><dd>{PART_LABEL[e.part]}{e.gadgets.length ? ` · ${e.gadgets.join(', ')}` : ''}</dd></div>
          <div><dt>Section</dt><dd className="num">{sectionLabel(e.start_s, e.length_s)}{e.crop_x != null ? ' · cropped to 9:16' : ''}</dd></div>
          <div><dt>Hook</dt><dd>“{e.hook}”</dd></div>
        </dl>
      ) : flagged ? (
        <p className={`work-flag ${d.state === 'waiting' || d.state === 'uploading' ? 'waiting' : 'failed'}`} role={d.state === 'failed' ? 'alert' : undefined}>
          <AlertTriangle size={15} aria-hidden="true" />
          <span>{dropLine(d, now)}</span>
        </p>
      ) : (
        <p className="work-now small" style={{ margin: 0 }}>
          {(d.state === 'uploading' || d.state === 'checking') && <Spinner />} <span>{dropLine(d, now)}</span>
        </p>
      )}

      {actions.length > 0 && (
        <div className="drop-actions">
          {actions.includes('make') && (
            <button type="button" className="btn primary" disabled={working} aria-busy={working} onClick={() => void make(null)}>
              {working && <Spinner />} Make it · <span className="num">about {dropCredits(d, d.adjust ?? {})} credits</span>
            </button>
          )}
          {actions.includes('adjust') && (
            <button type="button" className="btn ghost" disabled={working} onClick={() => setAdjusting(true)}>
              <SlidersHorizontal aria-hidden="true" /> Adjust
            </button>
          )}
          {actions.includes('retry-make') && (
            <button type="button" className="btn primary" disabled={working} aria-busy={working} onClick={() => void make(null)}>
              {working && <Spinner />} Try again · <span className="num">about {dropCredits(d, d.adjust ?? {})} credits</span>
            </button>
          )}
          {actions.includes('retry-check') && (
            <button type="button" className="btn line" disabled={working} onClick={() => void recheck()}>
              Try again
            </button>
          )}
          {actions.includes('remove') && (
            <button type="button" className="btn ghost" disabled={working} onClick={() => void remove()}>
              Remove
            </button>
          )}
        </div>
      )}

      {adjusting && (
        <AdjustSheet
          row={row}
          onClose={() => setAdjusting(false)}
          onMake={async (adjust) => {
            const ok = await make(adjust);
            if (ok) setAdjusting(false);
          }}
          working={working}
        />
      )}
    </article>
  );
}
