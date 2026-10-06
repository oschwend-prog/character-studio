// "In the works" (owner 2026-10-06: the core of the terminal is dropping our characters into his saved videos). At the top the
// Drop box ("Recommend" by default), then "Your drops": every dropped video in one table with a character menu per row (★ on
// the studio's recommendation) and Make it (DropsTable), then "Finished clips" with their players (FinishedClips), then any
// other approved pick on its way, grouped by character and sorted by its slot, else by when it was approved (v_tracker,
// migration 0010): the picture, what it is, the 8-step progress (done ticked, the current one lit, the rest muted), how long
// it has been at that step, the credits spent so far, and a red flag with the reason when it is stuck or something failed.
// The steps and flags come from trackerStep (lib/tracker.ts).
import { AlertTriangle, Check, ExternalLink } from 'lucide-react';
import { DropBox } from '../components/DropBox';
import { DropsTable } from '../components/DropsTable';
import { FinishedClips } from '../components/FinishedClips';
import { PickThumb } from '../components/PickThumb';
import { PostText } from '../components/PostText';
import { Avatar, Livery, Skeleton } from '../components/ui';
import { dropRows } from '../lib/drop';
import { finishedClips } from '../lib/finished';
import { formatCredits } from '../lib/format';
import { href, useNow } from '../lib/hooks';
import { compactCount } from '../lib/longlist';
import { ROSTER, activeRoster } from '../lib/roster';
import { TIER_LABELS } from '../lib/rules';
import { useStudio } from '../lib/store';
import {
  TRACKER_STEPS, groupTracker, inTracker, musicLabel, timeAtStep, trackerMode, trackerStep, trackerTier, trackerTitle, type TrackerStep,
} from '../lib/tracker';
import type { TrackerRow } from '../lib/types';


export function Works() {
  const { data } = useStudio();
  const now = useNow(60_000);
  if (!data) {
    return (
      <div className="page stack" aria-busy="true">
        <Skeleton h={160} />
        <Skeleton h={120} />
        <Skeleton h={300} />
      </div>
    );
  }
  const roster = data.characters.length ? data.characters.map((c) => ({ slug: c.slug, name: c.name })) : [...ROSTER];
  const drops = dropRows(data.tracker.filter((r) => inTracker(r, now)));
  const groups = groupTracker(data.tracker.filter((r) => !r.drop_card), roster, now);
  return (
    <div className="page stack">
      <div>
        <h1 className="h1">In the works</h1>
        <p className="small muted" style={{ margin: '6px 0 0' }}>
          Drop the videos you want made with our characters: the studio recommends who goes in, you can put any of them in. Every
          one, from the drop to the post: where it is, what it costs, and the finished clips to watch.
        </p>
      </div>
      <DropBox />
      <DropsTable rows={drops} roster={activeRoster(data.characters)} budget={data.budget} now={now} />
      <FinishedClips clips={finishedClips(data.library)} />
      {groups.length > 0 && (
        <div className="stack">
          <div>
            <h2 className="h2">Other picks in the works</h2>
            <p className="small muted" style={{ margin: '6px 0 0' }}>
              Approved in <a href={href('picks', undefined, { view: 'list' })}>Scan (Long list)</a>, on their 8 steps.
            </p>
          </div>
          {groups.map((g) => (
            <section key={g.slug ?? 'none'} className={`pick-sec ${g.slug ?? 'none'}`} data-char={g.slug ?? 'none'} aria-labelledby={`works-${g.slug ?? 'none'}`}>
              <header className="pick-sec-head">
                {g.slug ? <Avatar slug={g.slug} name={g.name} size={40} /> : <Livery slug={null} />}
                <h3 className="h2" id={`works-${g.slug ?? 'none'}`}>
                  {g.slug ? <a className="name-link" href={href('artist', g.slug)}>{g.name}</a> : g.name}
                </h3>
                <span className="stage-count num on" aria-label={`${g.rows.length} in the works`}>{g.rows.length}</span>
              </header>
              <div className="picks-grid stack" style={{ gap: 12 }}>
                {g.rows.map((r) => <WorkCard key={r.pick_id} row={r} now={now} />)}
              </div>
            </section>
          ))}
        </div>
      )}
    </div>
  );
}

function WorkCard({ row, now }: { row: TrackerRow; now: number }) {
  const s = trackerStep(row, now);
  const tier = trackerTier(row, now);
  const mode = trackerMode(row);
  const title = trackerTitle(row);
  const titleId = `work-${row.pick_id}`;
  const time = timeAtStep(s, now);
  const stepName = TRACKER_STEPS[s.step - 1];
  return (
    <article className="panel pick work" data-char={row.character_slug ?? 'none'} data-state={s.state} aria-labelledby={titleId}>
      <div className="work-top">
        <PickThumb pick={row} size="small" />
        <div className="pick-main">
          <div className="pick-badges">
            <span className={`tier-badge tier-${tier}`}>{TIER_LABELS[tier]}</span>
            {row.character_slug && <Livery slug={row.character_slug} />}
          </div>
          <h3 className="work-title" id={titleId}>{title}</h3>
          <p className="pick-meta" style={{ margin: 0 }}>
            <span>{mode === 'dropin' ? 'Drop-in' : mode === 'recreate' ? 'Recreate' : 'Analyst decides'}</span>
            <span>{musicLabel(row)}</span>
            <span className="num" title="Credits settled on this pick so far">{row.credits_spent > 0 ? `${formatCredits(row.credits_spent)} spent` : 'nothing spent yet'}</span>
          </p>
        </div>
      </div>

      <Stepper step={s} />

      <div className="work-status">
        <p className="work-now" style={{ margin: 0 }}>
          <b>
            {s.step}/8 · {stepName}
          </b>
          {s.note && <span>{s.step === 7 && row.post_scheduled_for ? `goes out ${s.note} (London)` : s.note}</span>}
          {time && <span className="muted num">{time}</span>}
        </p>
        {s.reason && (
          <p className={`work-flag ${s.state}`} role={s.state === 'failed' ? 'alert' : undefined}>
            {s.state !== 'dropped' && <AlertTriangle size={15} aria-hidden="true" />}
            <span>
              <b>{s.state === 'dropped' ? 'Dropped' : s.state === 'waiting' ? 'Waiting' : 'Failed'}</b>{' · '}
              {s.reason}
            </span>
          </p>
        )}
        {(s.action === 'queue' || (s.step === 8 && (row.post_url || row.latest_views != null))) && (
          <div className="work-links">
            {s.action === 'queue' && row.clip_id && (
              <a className="btn primary" href={href('queue', row.clip_id)}>
                Review in Queue
              </a>
            )}
            {s.step === 8 && row.post_url && /^https:/.test(row.post_url) && (
              <a className="btn ghost" href={row.post_url} target="_blank" rel="noopener noreferrer">
                View post <ExternalLink aria-hidden="true" />
              </a>
            )}
            {s.step === 8 && row.latest_views != null && <span className="small num">{compactCount(row.latest_views)} views</span>}
          </div>
        )}
      </div>

      {(s.step === 6 || s.step === 7) && row.clip_id && (row.caption || row.first_comment) && (
        <PostText caption={row.caption} hashtags={row.hashtags} firstComment={row.first_comment} />
      )}
    </article>
  );
}

function Stepper({ step }: { step: TrackerStep }) {
  return (
    <ol className="stepper" aria-label={`Step ${step.step} of 8: ${TRACKER_STEPS[step.step - 1]}`}>
      {TRACKER_STEPS.map((label, i) => {
        const n = i + 1;
        const phase = n < step.step || (n === step.step && step.done) ? 'done' : n === step.step ? 'current' : 'todo';
        const tone = phase === 'current' ? (step.action ? 'you' : step.state) : '';
        return (
          <li key={label} className={`step ${phase} ${tone}`} aria-current={n === step.step ? 'step' : undefined}>
            <span className="dot" aria-hidden="true">
              {phase === 'done' ? <Check size={12} /> : n}
            </span>
            <span className="step-name">
              {label}
              {phase === 'done' && <span className="sr-only"> (done)</span>}
            </span>
          </li>
        );
      })}
    </ol>
  );
}
