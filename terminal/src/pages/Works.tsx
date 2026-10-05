// "In the works": every approved pick from Picks until it is posted (v_tracker, migration 0010), grouped by character and sorted by
// its slot, else by when it was approved. Each card: the picture, what it is, the 8-step progress (done ticked, the current one lit,
// the rest muted), how long it has been at that step, the credits spent so far, and a red flag with the reason when it is stuck or
// something failed. The steps and flags come from trackerStep (lib/tracker.ts).
import { AlertTriangle, Check, ExternalLink } from 'lucide-react';
import { PickThumb } from '../components/PickThumb';
import { PostText } from '../components/PostText';
import { Avatar, Livery, Skeleton } from '../components/ui';
import { formatCredits } from '../lib/format';
import { href, useNow } from '../lib/hooks';
import { compactCount } from '../lib/longlist';
import { TIER_LABELS } from '../lib/rules';
import { useStudio } from '../lib/store';
import {
  TRACKER_STEPS, groupTracker, musicLabel, timeAtStep, trackerMode, trackerStep, trackerTier, trackerTitle, type TrackerStep,
} from '../lib/tracker';
import type { TrackerRow } from '../lib/types';

const LAUNCH = [
  { slug: 'biscuit', name: 'Biscuit' },
  { slug: 'reginald', name: 'Reginald' },
];

export function Works() {
  const { data } = useStudio();
  const now = useNow(60_000);
  if (!data) {
    return (
      <div className="page stack" aria-busy="true">
        <Skeleton h={120} />
        <Skeleton h={300} />
      </div>
    );
  }
  const roster = data.characters.length ? data.characters.map((c) => ({ slug: c.slug, name: c.name })) : LAUNCH;
  const groups = groupTracker(data.tracker, roster, now);
  return (
    <div className="page stack">
      <div>
        <h1 className="h1">In the works</h1>
        <p className="small muted" style={{ margin: '6px 0 0' }}>
          Every clip you approved, from the pick to the post: where it is, how long it has been there and what it has cost so far.
        </p>
      </div>
      {groups.length === 0 ? (
        <div className="panel empty">
          <b>Nothing approved yet.</b>
          <span className="muted small">
            Approve a clip in <a href={href('picks', undefined, { view: 'list' })}>Picks (Long list)</a> to start.
          </span>
        </div>
      ) : (
        groups.map((g) => (
          <section key={g.slug ?? 'none'} className={`pick-sec ${g.slug ?? 'none'}`} data-char={g.slug ?? 'none'} aria-labelledby={`works-${g.slug ?? 'none'}`}>
            <header className="pick-sec-head">
              {g.slug ? <Avatar slug={g.slug} name={g.name} size={40} /> : <Livery slug={null} />}
              <h2 className="h2" id={`works-${g.slug ?? 'none'}`}>{g.name}</h2>
              <span className="stage-count num on" aria-label={`${g.rows.length} in the works`}>{g.rows.length}</span>
            </header>
            <div className="picks-grid stack" style={{ gap: 12 }}>
              {g.rows.map((r) => (
                <WorkCard key={r.pick_id} row={r} now={now} />
              ))}
            </div>
          </section>
        ))
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
