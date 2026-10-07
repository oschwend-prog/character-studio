// Today: the daily dashboard (terminal v2, owner 2026-10-07). What needs the owner now as four counts (each a link to its
// list), tonight's departures with the one lit plate (Approve all), the last posts of every live character, what is left of
// the month's credits and, only when something is wrong, the alerts. Every action is one or two taps from here.
import { AlertTriangle, ArrowRight, CircleCheck, OctagonAlert } from 'lucide-react';
import { useMemo } from 'react';
import { Flap, Livery, PlatformCode, Section, Skeleton, Spinner, characterName } from '../components/ui';
import { creditsLeft, liveLastPosts, postNumbers, todayCounts, type TodayCounts } from '../lib/dashboard';
import { clipCode, formatCountdown, formatCredits, londonDate, platformName } from '../lib/format';
import { href, useNow } from '../lib/hooks';
import { useApproveAll } from '../lib/actions';
import { KILL_SWITCH_COPY, boardRows, selectApprovable, type BoardRow } from '../lib/rules';
import { useStudio } from '../lib/store';

export function Today() {
  const { data, busy } = useStudio();
  const approveAllClips = useApproveAll();
  const now = useNow(15_000);
  const rows = useMemo(() => (data ? boardRows(data.channels, data.queue, now) : []), [data, now]);

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

  const counts = todayCounts(data);
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

      <Tiles counts={counts} />

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
            <Board rows={rows} />
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
          {data.health.length > 0 && <Alerts />}
        </div>
      </div>
    </div>
  );
}

const plural = (n: number, one: string, many: string) => (n === 1 ? one : many);

/** The four counts, each a link to the list it counts. Amber while it is waiting for the owner, dim at zero. */
function Tiles({ counts }: { counts: TodayCounts }) {
  const tiles = [
    {
      key: 'pick', label: 'Pick a character', n: counts.needCharacter, wait: true,
      sub: plural(counts.needCharacter, 'clip needs a character', 'clips need a character'), to: href('clips', undefined, { f: 'pick' }),
    },
    {
      key: 'ready', label: 'Ready to make', n: counts.ready, wait: true,
      sub: counts.ready ? `${formatCredits(counts.readyCredits)} in all` : 'nothing ready', to: href('clips', undefined, { f: 'ready' }),
    },
    { key: 'making', label: 'Making now', n: counts.making, wait: false, sub: 'in production', to: href('videos') },
    {
      key: 'approve', label: 'To approve', n: counts.toApprove, wait: true,
      sub: plural(counts.toApprove, 'video waits for your OK', 'videos wait for your OK'), to: href('videos'),
    },
  ];
  return (
    <nav className="today-tiles" aria-label="What needs you">
      {tiles.map((t) => (
        <a key={t.key} className="panel today-tile" href={t.to} data-hot={t.wait && t.n > 0} data-zero={t.n === 0}>
          <span className="label">{t.label}</span>
          <span className="h1 num">{t.n}</span>
          <span className="small muted">{t.sub}</span>
        </a>
      ))}
    </nav>
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

function Board({ rows }: { rows: BoardRow[] }) {
  if (!rows.length) {
    return (
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

export function Alerts() {
  const { data } = useStudio();
  if (!data) return null;
  return (
    <Section id="alerts" title="Health" aside={data.health.length ? `${data.health.length} to look at` : undefined}>
      {data.health.length === 0 ? (
        <div className="all-clear">
          <CircleCheck aria-hidden="true" /> Daily run reported in, no failed posts, spend under 80%.
        </div>
      ) : (
        <div>
          {data.health.map((h, i) => (
            <div key={`${h.kind}-${h.ref_id ?? i}`} className={`alert-row ${h.severity}`}>
              {h.severity === 'critical' ? <OctagonAlert aria-label="Critical" /> : <AlertTriangle aria-label="Warning" />}
              <span>{tidy(h.message)}</span>
            </div>
          ))}
        </div>
      )}
    </Section>
  );
}
