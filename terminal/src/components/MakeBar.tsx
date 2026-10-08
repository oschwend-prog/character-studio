// The tick-and-make bar (terminal v3, spec 5.2 and 6; Review Focus 5). Nothing is ticked by default. With clips ticked it reads
// "Make 3 selected · 291 credits"; a tap opens the confirm on the page (not a browser dialog): the clips, the total, what is left
// of the month's cap and after. Only "Yes, make" asks Make it, for each clip one by one (useMakeMany), and the bar then shows each
// clip's own result: one refusal never hides the others. The steps are lib/makebar.ts's reducer, so a stray tap cannot skip the
// confirm.
import { Check, X } from 'lucide-react';
import { useCallback, useEffect, useRef, useState } from 'react';
import { useMakeMany } from '../lib/actions';
import { dropCredits, dropTitle } from '../lib/drop';
import { formatCredits } from '../lib/format';
import { href } from '../lib/hooks';
import {
  MAKE_BAR_START, confirmFacts, creditsWords, idsToSend, makeBarLabel, makeBarReducer, resultsHeading, type MakeBarEvent, type MakeBarState,
} from '../lib/makebar';
import { selectionTotal } from '../lib/ranking';
import { nameOf } from '../lib/roster';
import { useStudio } from '../lib/store';
import type { Budget, TrackerRow } from '../lib/types';
import { Sheet, Spinner } from './ui';

/** The ticked clips of one screen: nothing ticked at first; ticks survive a reload of the data (the bar keeps only live ones). */
export function useTicks() {
  const [ticked, setTicked] = useState<ReadonlySet<string>>(() => new Set());
  const toggle = useCallback((id: string, on: boolean) => {
    setTicked((s) => {
      const next = new Set(s);
      if (on) next.add(id);
      else next.delete(id);
      return next;
    });
  }, []);
  const untick = useCallback((ids: ReadonlyArray<string>) => {
    setTicked((s) => new Set([...s].filter((id) => !ids.includes(id))));
  }, []);
  const clear = useCallback(() => setTicked(new Set()), []);
  return { ticked, toggle, untick, clear };
}

const clipName = (r: TrackerRow | undefined, id: string) =>
  r ? `${dropTitle(r)}${r.character_slug ? ` (${r.character_name ?? nameOf(r.character_slug)})` : ''}` : `clip ${id.slice(0, 8)}`;

export function MakeBar({
  rows, selected, budget, onSent, onClear,
}: {
  /** Every row the ticks may point at: their prices and names. */
  rows: ReadonlyArray<TrackerRow>;
  /** The ticked clips that can still be made, in order (liveSelection). */
  selected: ReadonlyArray<string>;
  budget: Budget | null;
  /** The clips Make it was sent for: the screen unticks them. */
  onSent(ids: string[]): void;
  onClear(): void;
}) {
  const { busy } = useStudio();
  const makeMany = useMakeMany();
  const [state, setState] = useState<MakeBarState>(MAKE_BAR_START);
  const stateRef = useRef(state);
  stateRef.current = state;
  const dispatch = (e: MakeBarEvent) => setState((s) => makeBarReducer(s, e));
  const doneRef = useRef<HTMLUListElement>(null);
  // the names of the clips as they were when the confirm opened: a result still names its clip after the reload moved it on
  const [names, setNames] = useState<ReadonlyMap<string, string>>(new Map());

  // the sheet focuses its first button when it opens; the results take the focus when they replace the confirm's buttons
  useEffect(() => {
    if (state.step === 'done') doneRef.current?.focus();
  }, [state.step]);

  const byId = new Map(rows.map((r) => [r.pick_id, r]));
  const total = selectionTotal(rows, selected);

  const open = () => {
    setNames(new Map(selected.map((id) => [id, clipName(byId.get(id), id)])));
    dispatch({ type: 'open', ids: selected });
  };

  const send = async () => {
    const prev = stateRef.current;
    const next = makeBarReducer(prev, { type: 'send' });
    const ids = idsToSend(prev, next);
    if (!ids.length) return; // only the confirm's own button sends, and only once
    stateRef.current = next;
    setState(next);
    const results = await makeMany(ids);
    onSent(results.filter((r) => r.ok).map((r) => r.pickId));
    dispatch({ type: 'finished', results });
  };

  const sheet = state.step === 'pick' ? null : (
    <Sheet
      title={
        state.step === 'confirm' ? `Make ${state.ids.length === 1 ? 'this clip' : `these ${state.ids.length} clips`}?`
          : state.step === 'sending' ? 'Sending…' : resultsHeading(state.results)
      }
      onClose={() => dispatch({ type: state.step === 'confirm' ? 'cancel' : 'close' })} // while sending, neither applies: it stays open
    >
      {state.step === 'confirm' && <Confirm ids={state.ids} rows={rows} byId={byId} names={names} budget={budget} onSend={() => void send()} onBack={() => dispatch({ type: 'cancel' })} />}
      {state.step === 'sending' && (
        <p className="small" role="status" aria-live="polite" style={{ margin: 0 }}>
          <Spinner /> Asking for {state.ids.length === 1 ? 'the clip' : `the ${state.ids.length} clips`} one by one…
        </p>
      )}
      {state.step === 'done' && (
        <div className="sheet-body">
          <ul className="make-list results" aria-live="polite" tabIndex={-1} ref={doneRef} aria-label="Each clip">
            {state.results.map((r) => (
              <li key={r.pickId} data-ok={r.ok}>
                <span className="make-result-name">
                  {r.ok ? <Check size={15} aria-label="Sent" /> : <X size={15} aria-label="Refused" />} {names.get(r.pickId) ?? clipName(byId.get(r.pickId), r.pickId)}
                </span>
                <span className={r.ok ? 'muted small' : 'error-text'}>{r.message}</span>
              </li>
            ))}
          </ul>
          <div className="sheet-actions">
            {state.results.some((r) => r.ok) && (
              <a className="btn ghost" href={href('videos')} onClick={() => dispatch({ type: 'close' })}>
                See them in Videos
              </a>
            )}
            <button type="button" className="btn primary" onClick={() => dispatch({ type: 'close' })}>
              OK
            </button>
          </div>
        </div>
      )}
    </Sheet>
  );

  const bar = total.count > 0 ? (
    <div className="make-bar on" role="group" aria-label="Make the ticked clips">
      <span className="small num make-count">
        {total.count} ticked · about {formatCredits(total.credits)}
      </span>
      <div className="make-buttons">
        <button type="button" className="btn primary" disabled={busy.has('make-many')} onClick={open}>
          {makeBarLabel(total)}
        </button>
        <button type="button" className="btn ghost" onClick={onClear}>
          Clear
        </button>
      </div>
    </div>
  ) : (
    <div className="make-bar idle">
      <span className="small muted">Nothing ticked. Tick the clips you want made: the total shows here, and nothing is spent before you confirm.</span>
      <button type="button" className="btn primary" disabled>
        {makeBarLabel(total)}
      </button>
    </div>
  );
  // the sheet keeps its place whatever the bar shows (sent clips are unticked while the results are open)
  return (
    <>
      {bar}
      {sheet}
    </>
  );
}

/** The confirm (inside the sheet): the clips with their prices, the total, the month's budget left and the cap, then Yes or Back. */
function Confirm({
  ids, rows, byId, names, budget, onSend, onBack,
}: {
  ids: ReadonlyArray<string>;
  rows: ReadonlyArray<TrackerRow>;
  byId: ReadonlyMap<string, TrackerRow>;
  names: ReadonlyMap<string, string>;
  budget: Budget | null;
  onSend(): void;
  onBack(): void;
}) {
  const f = confirmFacts(rows, ids, budget);
  return (
    <div className="sheet-body">
      <ul className="make-list" aria-label="The clips">
        {ids.map((id) => {
          const r = byId.get(id);
          const price = r?.drop_card?.credits != null ? dropCredits(r.drop_card, r.drop_card.adjust ?? {}) : null;
          return (
            <li key={id}>
              <span>{names.get(id) ?? clipName(r, id)}</span>
              <span className="num muted">{price == null ? 'no price yet' : `about ${price} credits`}</span>
            </li>
          );
        })}
      </ul>
      <dl className="make-facts">
        <div>
          <dt>Total</dt>
          <dd className="num"><b>{creditsWords(f.credits)}</b></dd>
        </div>
        <div>
          <dt>Left this month</dt>
          <dd className="num">{f.left == null ? 'could not be read' : `${formatCredits(f.left)} of the ${formatCredits(f.cap)} cap`}</dd>
        </div>
        {f.leftAfter != null && (
          <div>
            <dt>Left after these</dt>
            <dd className={`num${f.leftAfter < 0 ? ' error-text' : ''}`}>{formatCredits(Math.max(0, f.leftAfter))}</dd>
          </div>
        )}
      </dl>
      {f.blocked ? (
        <p className="error-text" role="alert" style={{ margin: 0 }}>
          {f.blocked}
          {budget?.kill_switch && <> <a href={href('more', 'budget')}>Budget</a></>}
        </p>
      ) : (
        <p className="hint" style={{ margin: 0 }}>
          Each clip is made like its own Make it, at the price shown. The studio still stops at the monthly cap.
        </p>
      )}
      <div className="sheet-actions">
        <button type="button" className="btn ghost" onClick={onBack}>
          Back
        </button>
        <button type="button" className="btn primary" disabled={Boolean(f.blocked)} onClick={onSend}>
          Yes, make {f.count} · {creditsWords(f.credits)}
        </button>
      </div>
    </div>
  );
}
