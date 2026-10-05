// Queue: one finished clip at a time, thumb-reachable. Watch it, edit hook and caption, then Approve
// (next slot), Schedule (a time you pick), Reject (with a reason) or Regenerate (a note for tomorrow).
import { CalendarClock, ChevronLeft, ChevronRight, ExternalLink, RotateCcw, X } from 'lucide-react';
import { useEffect, useRef, useState, type FormEvent } from 'react';
import { Flap, Livery, Skeleton, Spinner, characterName } from '../components/ui';
import { clipCode, formatCredits, isoToLondonWall, londonStamp, londonWallToIso, platformName } from '../lib/format';
import { href } from '../lib/hooks';
import { useApproveAll } from '../lib/actions';
import { SLOT_RULE, captionEdit, nextCurrentId, selectApprovable } from '../lib/rules';
import { useStudio } from '../lib/store';
import type { QueueClip } from '../lib/types';

const REJECT_REASONS = ['Eyes swapped', 'Outfit or identity off', 'Hands or paws melt', 'Source leaked through', 'Hook is weak'];

export function Queue({ focus }: { focus: string | null }) {
  const { data, backend, busy } = useStudio();
  const approveAll = useApproveAll();
  const queue = data?.queue ?? [];
  const ids = queue.map((c) => c.id);
  // Which clip is on screen is decided by nextCurrentId alone: computed during render (so the very first
  // render of a deep link already shows that clip) and written back in a single effect.
  const [currentId, setCurrentId] = useState<string | null>(null);
  const appliedFocus = useRef<string | null>(null);
  const shown = nextCurrentId({ ids, currentId, focus, appliedFocus: appliedFocus.current });
  useEffect(() => {
    appliedFocus.current = shown.appliedFocus;
    if (shown.id !== currentId) setCurrentId(shown.id);
  }, [shown.id, shown.appliedFocus, currentId]);
  const index = Math.max(0, shown.id ? ids.indexOf(shown.id) : 0);
  const clip = queue[index];
  const go = (i: number) => {
    const next = queue[i];
    if (!next) return;
    setCurrentId(next.id);
    window.history.replaceState(null, '', href('queue', next.id)); // a reload reopens this clip
  };

  if (!data) {
    return (
      <div className="page stack" aria-busy="true">
        <Skeleton h={420} />
      </div>
    );
  }

  const inFlight = new Set([...busy].filter((k) => k.startsWith('clip-')).map((k) => k.slice(5)));
  const approvable = selectApprovable(queue, inFlight);

  return (
    <div className="page stack">
      <div style={{ display: 'flex', alignItems: 'center', gap: 12, flexWrap: 'wrap' }}>
        <h1 className="h1">Queue</h1>
        <Flap text={String(queue.length).padStart(2, '0')} tone={queue.length ? 'action' : 'muted'} label={`${queue.length} waiting`} />
        <span className="grow" style={{ flex: 1 }} />
        {queue.length > 1 && (
          <button
            type="button"
            className="btn line"
            disabled={!approvable.ids.length || busy.has('approve-all')}
            aria-busy={busy.has('approve-all')}
            onClick={() => approveAll(approvable.ids)}
          >
            {busy.has('approve-all') && <Spinner />} Approve all {approvable.ids.length}
          </button>
        )}
      </div>

      {!clip ? (
        <div className="panel empty">
          <b>Nothing waiting</b>
          <span className="muted small">
            Finished clips land here after QA. Channels on autopilot skip this queue and post at their next slot.
          </span>
          <a className="link" href={href('today')}>
            Back to today’s board
          </a>
        </div>
      ) : (
        <>
          <div className="pager">
            <button type="button" className="btn ghost" onClick={() => go(index - 1)} disabled={index === 0} aria-label="Previous clip">
              <ChevronLeft aria-hidden="true" /> Prev
            </button>
            <span className="pos" aria-live="polite">
              {clipCode(clip.id, clip.character_slug)} · {index + 1} of {queue.length}
            </span>
            <button type="button" className="btn ghost" onClick={() => go(index + 1)} disabled={index >= queue.length - 1} aria-label="Next clip">
              Next <ChevronRight aria-hidden="true" />
            </button>
          </div>
          <ClipView key={clip.id} clip={clip} demo={backend.kind === 'demo'} />
        </>
      )}
    </div>
  );
}

function Player({ clip, demo }: { clip: QueueClip; demo: boolean }) {
  const { backend } = useStudio();
  const [src, setSrc] = useState<string | null>(null);
  const [state, setState] = useState<'loading' | 'ready' | 'none'>('loading');
  useEffect(() => {
    let live = true;
    if (!clip.master_path) {
      setState('none');
      return;
    }
    backend.signedUrl(clip.master_path).then((u) => {
      if (!live) return;
      setSrc(u);
      setState(u ? 'ready' : 'none');
    });
    return () => {
      live = false;
    };
  }, [backend, clip.master_path]);

  return (
    <div className="player">
      {state === 'ready' && src ? (
        <video src={src} controls playsInline loop preload="metadata" aria-label={`Clip ${clipCode(clip.id, clip.character_slug)}: ${clip.hook ?? ''}`} />
      ) : (
        <div className={`stand-in ${clip.character_slug}`} role="img" aria-label={demo ? 'Demo stand-in frame: no video in demo mode' : 'No playable master'}>
          <span className="top">
            <span className="note">{state === 'loading' ? 'Loading master…' : demo ? 'Demo stand-in · no video' : 'No master file to play'}</span>
            <span className="bug" aria-hidden="true">
              <i />
              <i />
            </span>
          </span>
          <span className="hookline">{clip.hook}</span>
          <span />
        </div>
      )}
    </div>
  );
}

type Mode = null | 'schedule' | 'reject' | 'regenerate';

function ClipView({ clip, demo }: { clip: QueueClip; demo: boolean }) {
  const { backend, run, busy } = useStudio();
  const [hook, setHook] = useState(clip.hook ?? '');
  const [caption, setCaption] = useState(clip.caption ?? '');
  const [mode, setMode] = useState<Mode>(null);
  const [when, setWhen] = useState(() => isoToLondonWall(clip.next_slot ?? Date.now() + 3600_000));
  const [reason, setReason] = useState('');
  const key = `clip-${clip.id}`;
  const working = busy.has(key);
  // Never '' over the wire: a blank field means "keep what is there" (approve_clip does the same).
  const edits = { hook: captionEdit(hook, clip.hook), caption: captionEdit(caption, clip.caption) };
  const targets = clip.targets.map((t) => `${platformName(t.platform)} ${t.handle ?? ''}`.trim()).join(' · ');
  const noTarget = clip.targets.length === 0;
  const blocked = clip.blocked_reason ?? (!clip.master_path ? 'no master file yet' : noTarget ? 'no connected account can take it' : null);
  const qaProblems = clip.qa?.problems?.length ? clip.qa.problems.join('; ') : null;

  const approve = () =>
    run(key, () => backend.approveClip(clip.id, edits), `Approved for ${clip.next_slot ? londonStamp(clip.next_slot) : 'the next slot'}. ${SLOT_RULE}.`);
  const schedule = (e: FormEvent) => {
    e.preventDefault();
    let at: string;
    try {
      at = londonWallToIso(when);
    } catch {
      return;
    }
    void run(key, () => backend.approveClip(clip.id, { ...edits, scheduleAt: at }), `Scheduled for ${londonStamp(at)}`);
  };
  const reject = (e: FormEvent) => {
    e.preventDefault();
    void run(key, () => backend.rejectClip(clip.id, reason), 'Rejected: the reason goes to QA and the playbook');
  };
  const regenerate = (e: FormEvent) => {
    e.preventDefault();
    void run(key, () => backend.regenerateClip(clip.id, reason.trim() || null), 'Sent back: the next daily run remakes it');
  };

  return (
    <div className="clip-view">
      <Player clip={clip} demo={demo} />
      <div className="stack" style={{ gap: 14 }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
          <Livery slug={clip.character_slug} />
          <b>{characterName(clip.character_slug)}</b>
          <span className="tag">{clip.mode}</span>
          {clip.pick_url && (
            <a className="link" href={clip.pick_url} target="_blank" rel="noopener noreferrer">
              from a Viral Pick <ExternalLink size={13} aria-hidden="true" />
            </a>
          )}
        </div>

        <div className="facts">
          <div>
            <span className="label">Goes to</span>
            <span className="v" style={noTarget ? { color: 'var(--red)' } : undefined}>{noTarget ? 'No connected account yet' : targets}</span>
          </div>
          <div>
            <span className="label">Next slot</span>
            <span className="v num">{clip.next_slot ? londonStamp(clip.next_slot) : '—'}</span>
          </div>
          <div>
            <span className="label">Cost</span>
            <span className="v num">{formatCredits(clip.cost_credits)}</span>
          </div>
          <div>
            <span className="label">QA</span>
            <span className="v">{qaProblems ?? (clip.qa?.visual as string) ?? clip.qa?.tech ?? '—'}</span>
          </div>
          {(clip.source_credit || clip.source_trend) && (
            <div style={{ gridColumn: '1 / -1' }}>
              <span className="label">Source</span>
              <span className="v">
                {[clip.source_kind?.replace('_', ' '), clip.source_credit && `trend: ${clip.source_credit}`, clip.source_trend].filter(Boolean).join(' · ')}
              </span>
            </div>
          )}
        </div>

        <div className="field">
          <label className="label" htmlFor={`hook-${clip.id}`}>Hook on screen</label>
          <input id={`hook-${clip.id}`} className="input" value={hook} onChange={(e) => setHook(e.target.value)} />
          <span className="hint">
            {hook.trim() ? 'The hook is burnt into the master; an edit here is stored for the record and the caption.' : 'Empty: the original hook is kept.'}
          </span>
        </div>
        <div className="field">
          <label className="label" htmlFor={`cap-${clip.id}`}>Caption</label>
          <textarea id={`cap-${clip.id}`} className="textarea" value={caption} onChange={(e) => setCaption(e.target.value)} />
          <span className="hint">{caption.trim() ? 'The AI-generated label is added when it posts.' : 'Empty: the original caption is kept.'}</span>
        </div>

        {mode === 'schedule' && (
          <form className="inline-form" onSubmit={schedule} aria-label="Schedule this clip">
            <label className="label" htmlFor={`when-${clip.id}`}>Post at (London time)</label>
            <input id={`when-${clip.id}`} className="input" type="datetime-local" value={when} min={isoToLondonWall(Date.now())} onChange={(e) => setWhen(e.target.value)} required />
            <span className="hint">At most 2 posts per channel per day: a third waits for the next slot.</span>
            <div className="row">
              <button type="button" className="btn ghost" onClick={() => setMode(null)}>Cancel</button>
              <button type="submit" className="btn primary" disabled={working || Boolean(blocked)} aria-busy={working}>
                {working && <Spinner />} Approve for this time
              </button>
            </div>
          </form>
        )}
        {(mode === 'reject' || mode === 'regenerate') && (
          <form className="inline-form" onSubmit={mode === 'reject' ? reject : regenerate} aria-label={mode === 'reject' ? 'Reject this clip' : 'Regenerate this clip'}>
            <span className="label">{mode === 'reject' ? 'Why reject? (required)' : 'What should change? (optional)'}</span>
            <div className="chips">
              {REJECT_REASONS.map((r) => (
                <button key={r} type="button" className="chip" aria-pressed={reason === r} onClick={() => setReason(r)}>
                  {r}
                </button>
              ))}
            </div>
            <label className="sr-only" htmlFor={`why-${clip.id}`}>{mode === 'reject' ? 'Reason' : 'Note'}</label>
            <input id={`why-${clip.id}`} className="input" value={reason} onChange={(e) => setReason(e.target.value)} placeholder="Or in your words" />
            <div className="row">
              <button type="button" className="btn ghost" onClick={() => setMode(null)}>Cancel</button>
              {mode === 'reject' ? (
                <button type="submit" className="btn danger solid" disabled={working || !reason.trim()} aria-busy={working}>
                  {working && <Spinner />} Reject clip
                </button>
              ) : (
                <button type="submit" className="btn line" disabled={working} aria-busy={working}>
                  {working && <Spinner />} Remake tomorrow
                </button>
              )}
            </div>
          </form>
        )}

        {mode === null && (
          <div className="dock">
          {blocked && (
            <p className="error-text" role="status" style={{ margin: '0 0 8px' }}>
              Can't approve yet: {blocked}.
            </p>
          )}
          <div className="actions">
            <button type="button" className="btn primary wide" onClick={approve} disabled={working || Boolean(blocked)} aria-busy={working}>
              {working && <Spinner />} Approve · next slot
            </button>
            <button type="button" className="btn line" onClick={() => setMode('schedule')} disabled={working || Boolean(blocked)}>
              <CalendarClock aria-hidden="true" /> Schedule
            </button>
            <button type="button" className="btn line" onClick={() => { setReason(''); setMode('regenerate'); }} disabled={working} aria-label="Regenerate: remake it in the next daily run">
              <RotateCcw aria-hidden="true" /> Remake
            </button>
            <button type="button" className="btn danger" onClick={() => { setReason(''); setMode('reject'); }} disabled={working}>
              <X aria-hidden="true" /> Reject
            </button>
          </div>
          </div>
        )}
      </div>
    </div>
  );
}
