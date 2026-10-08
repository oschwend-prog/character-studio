// Today: the daily dashboard (terminal v2, owner 2026-10-07; v3 2026-10-07). First the studio at a glance (every live character's
// clips, views, next post, runway and test status), then Make these (each character's best ready clips, ranked, with the
// tick-and-make bar), then Approve these (the finished videos waiting for his OK), then tonight's departures with the one lit
// plate (Approve all), the last posts of every live character, what is left of the month's credits and, only when something is
// wrong, the alerts. Every action is one or two taps from here.
import { AlertTriangle, ArrowRight, CircleCheck, OctagonAlert } from 'lucide-react';
import { useMemo } from 'react';
import { DropThumb } from '../components/DropsTable';
import { Glance } from '../components/Glance';
import { MakeBar, useTicks } from '../components/MakeBar';
import { PickThumb } from '../components/PickThumb';
import { RankedClips } from '../components/RankedClips';
import { Flap, Livery, PlatformCode, Section, Skeleton, Spinner, characterName } from '../components/ui';
import { clipChip } from '../lib/clipstatus';
import { creditsLeft, hasWarnings, liveChannels, liveLastPosts, postNumbers, problemClips, problemClipsLine } from '../lib/dashboard';
import { clipCode, formatAge, formatCountdown, formatCredits, londonDate, platformName } from '../lib/format';
import { approvalOrder } from '../lib/glance';
import { href, useNow } from '../lib/hooks';
import { useApproveAll } from '../lib/actions';
import { liveSelection } from '../lib/makebar';
import { liveryClass, orderRoster } from '../lib/roster';
import { KILL_SWITCH_COPY, boardRows, selectApprovable, type BoardRow } from '../lib/rules';
import { useStudio } from '../lib/store';
import { inTracker } from '../lib/tracker';
import type { QueueClip } from '../lib/types';

export function Today() {
  const { data, busy } = useStudio();
  const approveAllClips = useApproveAll();
  const now = useNow(15_000);
  // Tonight is per live character: a designing, paused or retired character's channels stay off the board
  const rows = useMemo(() => (data ? boardRows(liveChannels(data.channels), data.queue, now) : []), [data, now]);

  if (!data) {
    return (
      <div className="page stack" aria-busy="true">
        <Skeleton h={90} />
        <Skeleton h={240} />
      </div>
    );
  }

  const next = rows.find((r) => r.at && Date.parse(r.at) > now && r.status !== 'NOT LINKED');
  const together = next ? rows.filter((r) => r.at === next.at) : [];
  const inFlight = new Set([...busy].filter((k) => k.startsWith('clip-')).map((k) => k.slice(5)));
  const approvable = selectApprovable(data.queue, inFlight);
  const approveAll = () => approveAllClips(approvable.ids);

  const killSwitch = data.budget?.kill_switch === true;

  return (
    <div className="page stack">
      {killSwitch && (
        <div className="panel kill on" role="alert">
          <p className="small" style={{ margin: 0, color: 'var(--red)' }}>
            {KILL_SWITCH_COPY.today}
          </p>
          <a className="link" href={href('more', 'budget')}>
            Budget <ArrowRight size={14} aria-hidden="true" />
          </a>
        </div>
      )}

      <Glance now={now} />

      <div className="today-grid">
        <MakeThese now={now} />
        <ApproveThese now={now} />
      </div>

      <div className="today-grid">
        <div className="stack">
          <Section id="tonight" title="Tonight" aside={<span className="num">{londonDate(now)} · London time</span>}>
            {next ? (
              <div className="departure" aria-label={`Next post ${next.time} London, ${formatCountdown(next.at!, now)}`}>
                <Flap text={next.time} size="big" tone={next.tone === 'action' ? 'action' : undefined} />
                <div className="meta">
                  <span className="count num">in {formatCountdown(next.at!, now)}</span>
                  <span className="what">
                    {characterName(next.characterSlug)} · {together.map((r) => platformName(r.platform)).join(' + ')}
                    {next.today ? '' : ` · ${next.day}`}
                  </span>
                </div>
              </div>
            ) : (
              <div className="departure">
                <Flap text="--:--" size="big" tone="muted" />
                <div className="meta">
                  <span className="count">Nothing booked</span>
                  <span className="what">No connected channel has a slot coming up.</span>
                </div>
              </div>
            )}
            <Board rows={rows} anyChannel={data.channels.length > 0} />
          </Section>

          {data.queue.length > 0 && (
            <div className="needs" role="region" aria-label="Clips waiting for you">
              <div className="text">
                <span className="count" aria-hidden="true">{data.queue.length}</span>
                <b>{data.queue.length === 1 ? 'clip waits for you' : 'clips wait for you'}</b>
                <span>
                  {approvable.skipped.length
                    ? `${approvable.skipped.length} can't go yet: ${approvable.skipped[0].reason}`
                    : 'QA passed · next slot; a 3rd for one character that day waits a slot'}
                </span>
              </div>
              <div className="go">
                <a className="review" href={href('videos')}>
                  Review
                </a>
                <button
                  type="button"
                  className="btn"
                  onClick={approveAll}
                  disabled={!approvable.ids.length || busy.has('approve-all')}
                  aria-busy={busy.has('approve-all')}
                >
                  {busy.has('approve-all') ? <Spinner /> : null}
                  Approve all{approvable.ids.length ? ` ${approvable.ids.length}` : ''}
                </button>
              </div>
            </div>
          )}
        </div>

        <div className="stack">
          <LastPosts />
          <CreditsLine />
          {hasWarnings(data) && <Alerts />}
        </div>
      </div>
    </div>
  );
}

/**
 * Make these (spec 5.2): per live character his top 3 ready clips by score, with rank, score, reason and price; tick the ones to
 * make and the bar adds them up, then asks once more with the total, the month's budget left and the cap. Nothing is ticked first.
 */
function MakeThese({ now }: { now: number }) {
  const { data } = useStudio();
  const { ticked, toggle, untick, clear } = useTicks();
  const rows = useMemo(() => (data ? data.tracker.filter((r) => r.drop_card && inTracker(r, now)) : []), [data, now]);
  const live = useMemo(() => orderRoster((data?.characters ?? []).filter((c) => c.status === 'live')), [data]);
  if (!data) return null;
  // only the clips this block shows can be ticked here: each character's top 3 Ready ones
  const makeable = new Set(rows.filter((r) => clipChip(r) === 'ready').map((r) => r.pick_id));
  const selected = liveSelection(ticked, makeable);
  return (
    <Section id="make-these" title="Make these" aside={<a href={href('clips')}>All clips <ArrowRight size={14} aria-hidden="true" /></a>}>
      <p className="small muted" style={{ margin: 0 }}>
        Each character’s best ready clips, ranked by the free check’s score (how likely the clip gets views with him in it). Tick the
        ones to make: the price shows first, and nothing is spent before you confirm.
      </p>
      <div className="make-scope">
        <RankedClips compact rows={rows} characters={live} ticked={ticked} onTick={toggle} now={now} />
        <MakeBar rows={rows} selected={selected} budget={data.budget} onSent={untick} onClear={clear} />
      </div>
    </Section>
  );
}

/** Approve these (spec 5.3): the finished videos waiting for his OK, the newest first, each with a Review button to the Queue. */
function ApproveThese({ now }: { now: number }) {
  const { data } = useStudio();
  if (!data) return null;
  const queue = approvalOrder(data.queue);
  return (
    <Section id="approve-these" title="Approve these" aside={queue.length ? <span className="num">{queue.length}</span> : undefined}>
      {queue.length === 0 ? (
        <p className="small muted" style={{ margin: 0 }}>
          Nothing to approve. Finished videos land here.
        </p>
      ) : (
        <ul className="pipe-list approve-list" aria-label="Videos waiting for your OK">
          {queue.map((q) => (
            <li key={q.id} className="pipe-row" data-char={q.character_slug}>
              <QueueThumb clip={q} />
              <div className="pipe-main">
                <b className="pipe-hook">{q.hook ? `“${q.hook}”` : 'untitled video'}</b>
                <div className="pipe-meta">
                  <Livery slug={q.character_slug} />
                  <span>{q.character_name || characterName(q.character_slug)}</span>
                  <span>made {formatAge(q.created_at, now)}</span>
                  {q.blocked_reason && <span className="tag alert">can’t go yet</span>}
                </div>
              </div>
              <a className="btn primary" href={href('videos', q.id)} aria-label={`Review ${q.hook ?? 'this video'}`}>
                Review
              </a>
            </li>
          ))}
        </ul>
      )}
    </Section>
  );
}

/** A finished video's picture: the frames of the clip it came from (its drop), else the pick's picture, else his colour. */
function QueueThumb({ clip }: { clip: QueueClip }) {
  const { data } = useStudio();
  const row = clip.pick_id ? data?.tracker.find((r) => r.pick_id === clip.pick_id) : undefined;
  if (row?.drop_card) return <DropThumb row={row} />;
  if (row) return <PickThumb pick={row} size="small" />;
  return (
    <div className="thumb small" aria-hidden="true">
      <span className={`stand-in ${liveryClass(clip.character_slug)}`}>
        <span className="bug"><i /><i /></span>
      </span>
    </div>
  );
}

/** The latest posts of every live character with their numbers; one quiet line until the first post is out. */
function LastPosts() {
  const { data } = useStudio();
  const groups = useMemo(() => (data ? liveLastPosts(data) : []), [data]);
  const any = groups.some((g) => g.posts.length > 0);
  return (
    <Section id="last-posts" title="Last posts">
      {!any ? (
        <p className="small muted" style={{ margin: 0 }}>
          Views, likes and shares appear here after the first posts.
        </p>
      ) : (
        <div className="panel rows">
          {groups.map((g) => (
            <div key={g.slug} className="panel-pad">
              <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
                <Livery slug={g.slug} />
                <b style={{ fontSize: 14 }}>{g.name}</b>
              </div>
              {g.posts.length === 0 ? (
                <p className="small muted" style={{ margin: '6px 0 0' }}>No posts yet.</p>
              ) : (
                <ul className="pipe-list" aria-label={`${g.name}’s last posts`}>
                  {g.posts.map((p) => {
                    const title = p.hook ?? clipCode(p.clipId, g.slug);
                    return (
                      <li key={p.clipId} className="pipe-row">
                        <div className="pipe-main">
                          <b className="pipe-hook">{title}</b>
                          <div className="pipe-meta">
                            {p.postedAt && <span>{londonDate(p.postedAt)}</span>}
                            <span className="num">{postNumbers(p)}</span>
                          </div>
                        </div>
                        <a className="btn line" href={href('characters', 'all', { clip: p.clipId })} aria-label={`Open ${title}`}>
                          Open
                        </a>
                      </li>
                    );
                  })}
                </ul>
              )}
            </div>
          ))}
        </div>
      )}
    </Section>
  );
}

/** What is left of the month's credits, one line (the whole picture is on More, Budget). */
function CreditsLine() {
  const { data } = useStudio();
  const left = creditsLeft(data?.budget);
  if (left == null || !data?.budget) return null;
  return (
    <Section id="credits" title="Credits" aside={<a href={href('more', 'budget')}>Budget <ArrowRight size={14} aria-hidden="true" /></a>}>
      <div style={{ display: 'flex', alignItems: 'baseline', gap: 8, flexWrap: 'wrap' }}>
        <span className="h1 num">{formatCredits(left)}</span>
        <span className="small muted num">left this month · of {formatCredits(data.budget.cap)}</span>
      </div>
    </Section>
  );
}

function Board({ rows, anyChannel }: { rows: BoardRow[]; anyChannel: boolean }) {
  if (!rows.length) {
    return anyChannel ? (
      <div className="empty">
        <b>No live character yet</b>
        <span className="muted small">A character's channels appear here once his status is live.</span>
      </div>
    ) : (
      <div className="empty">
        <b>No channels yet</b>
        <span className="muted small">
          Accounts appear here once <code>bin/studio seed</code> has run with their handles and Postiz ids.
        </span>
      </div>
    );
  }
  return (
    <div className="board" role="table" aria-label="Today's departures">
      <div className="board-head" role="row">
        <span className="label" role="columnheader">Time</span>
        <span className="label" role="columnheader">Char</span>
        <span className="label" role="columnheader">Gate</span>
        <span className="label" role="columnheader">Status</span>
      </div>
      {rows.map((r) => {
        const target = r.status === 'NEEDS YOU' && r.clipId ? href('videos', r.clipId) : r.clipId ? href('characters', 'all', { clip: r.clipId }) : null;
        const cells = (
          <>
            <span role="cell">
              <Flap text={r.today ? r.time : r.day.slice(0, 3)} tone={r.today ? undefined : 'muted'} label={r.today ? r.time : `${r.day} ${r.time}`} />
            </span>
            <span role="cell">
              <Livery slug={r.characterSlug} />
            </span>
            <span role="cell">
              <PlatformCode platform={r.platform} />
            </span>
            <span role="cell" className="status">
              <Flap text={r.status} tone={r.tone} cells={9} />
            </span>
            <span role="cell" className="sub">
              {r.clipId && <span className="code">{clipCode(r.clipId, r.characterSlug)}</span>}
              {target ? (
                <a
                  className="hook row-link"
                  href={target}
                  aria-label={`${r.status === 'NEEDS YOU' ? 'Review' : 'Open'} ${clipCode(r.clipId!, r.characterSlug)}: ${r.hook ?? ''}`}
                >
                  {r.hook ?? r.handle ?? 'open'}
                </a>
              ) : (
                <span className="hook">
                  {r.hook ?? (r.status === 'NEXT' ? `${r.day} ${r.time} · ${r.handle ?? 'no handle yet'}` : r.handle ?? 'no handle yet')}
                </span>
              )}
            </span>
          </>
        );
        return target ? (
          <div key={r.accountId} role="row" className="board-row tappable">
            {cells}
          </div>
        ) : (
          <div key={r.accountId} role="row" className={`board-row${r.status === 'NEXT' || r.status === 'NOT LINKED' ? ' dim' : ''}`}>
            {cells}
          </div>
        );
      })}
    </div>
  );
}

const tidy = (m: string) => m.replace(' is needs_check', ' needs a check').replace(' is failed', ' failed');

/** Health: what v_health reports plus the dropped clips that are blocked or failed (they are not in v_health). */
export function Alerts() {
  const { data } = useStudio();
  if (!data) return null;
  const clips = problemClips(data);
  const count = data.health.length + (clips > 0 ? 1 : 0);
  return (
    <Section id="alerts" title="Health" aside={count ? `${count} to look at` : undefined}>
      {count === 0 ? (
        <div className="all-clear">
          <CircleCheck aria-hidden="true" /> Daily run reported in, no failed posts or clips, spend under 80%.
        </div>
      ) : (
        <div>
          {data.health.map((h, i) => (
            <div key={`${h.kind}-${h.ref_id ?? i}`} className={`alert-row ${h.severity}`}>
              {h.severity === 'critical' ? <OctagonAlert aria-label="Critical" /> : <AlertTriangle aria-label="Warning" />}
              <span>{tidy(h.message)}</span>
            </div>
          ))}
          {clips > 0 && (
            <div className="alert-row warning">
              <AlertTriangle aria-label="Warning" />
              <span>
                <a href={href('clips', undefined, { v: 'all', f: 'problems' })}>{problemClipsLine(clips)}</a>
              </span>
            </div>
          )}
        </div>
      )}
    </Section>
  );
}
