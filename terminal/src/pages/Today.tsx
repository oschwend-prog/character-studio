// Today: the departures board. What goes out today per channel, the one lit plate for what needs the
// owner (Approve all), picks, spend, autopilot and alerts. Every action is one or two taps from here.
import { AlertTriangle, ArrowRight, CircleCheck, OctagonAlert } from 'lucide-react';
import { useMemo } from 'react';
import { AutopilotSwitch, Flap, Livery, PlatformCode, Section, Skeleton, Spinner, characterName } from '../components/ui';
import { clipCode, formatCountdown, formatCredits, londonDate, platformName } from '../lib/format';
import { href, useNow } from '../lib/hooks';
import { boardRows, selectApprovable, spendState, type BoardRow } from '../lib/rules';
import { useStudio } from '../lib/store';
import type { Channel } from '../lib/types';

export function Today() {
  const { data, backend, run, busy } = useStudio();
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
  const approveAll = () =>
    run(
      'approve-all',
      async () => {
        const failed: string[] = [];
        for (const id of approvable.ids) {
          try {
            await backend.approveClip(id);
          } catch (e) {
            failed.push(e instanceof Error ? e.message : String(e));
          }
        }
        if (failed.length) throw new Error(`${approvable.ids.length - failed.length} approved, ${failed.length} refused: ${failed[0]}`);
      },
      `${approvable.ids.length} approved: each posts at its next slot`,
    );

  return (
    <div className="page">
      <div className="today-grid">
        <div className="stack">
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

          <Section id="board" title={`Departures · ${londonDate(now)}`} aside={<span className="num">London time</span>}>
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
                    : 'QA passed · each posts at its next slot'}
                </span>
              </div>
              <div className="go">
                <a className="review" href={href('queue')}>
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
          <PicksLine />
          <SpendLine />
          <AutopilotBlock channels={data.channels} />
          <Alerts />
        </div>
      </div>
    </div>
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
        const target = r.status === 'NEEDS YOU' && r.clipId ? href('queue', r.clipId) : r.clipId ? href('library', r.clipId) : null;
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
              <span className="hook">
                {r.hook ?? (r.status === 'NEXT' ? `${r.day} ${r.time} · ${r.handle ?? 'no handle yet'}` : r.handle ?? 'no handle yet')}
              </span>
            </span>
          </>
        );
        return target ? (
          <a key={r.accountId} role="row" className="board-row tappable" href={target}>
            {cells}
          </a>
        ) : (
          <div key={r.accountId} role="row" className={`board-row${r.status === 'NEXT' || r.status === 'NOT LINKED' ? ' dim' : ''}`}>
            {cells}
          </div>
        );
      })}
    </div>
  );
}

function PicksLine() {
  const { data } = useStudio();
  if (!data) return null;
  const best = data.picks[0];
  return (
    <Section id="picks-line" title="Viral Picks" aside={<a href={href('picks')}>Open <ArrowRight size={14} aria-hidden="true" /></a>}>
      <a className="board-row tappable" href={href('picks')} style={{ gridTemplateColumns: 'auto 1fr', minHeight: 64 }}>
        <Flap text={String(data.picks.length).padStart(2, '0')} size="mid" tone={data.picks.length ? 'action' : 'muted'} label={`${data.picks.length} new picks`} />
        <span style={{ display: 'flex', flexDirection: 'column', gap: 2, minWidth: 0 }}>
          <span>{data.picks.length === 1 ? 'new pick to decide' : 'new picks to decide'}</span>
          {best && (
            <span className="small muted" style={{ overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
              Best {best.total_score ?? '—'}: “{best.hook ?? best.url}”
            </span>
          )}
        </span>
      </a>
      <p className="small muted" style={{ margin: 0 }}>
        Picks autopilot is on: the standing rule approves 80+ with feasibility 7+ and skips under 65. The rest waits here.
      </p>
    </Section>
  );
}

function SpendLine() {
  const { data } = useStudio();
  const b = data?.budget;
  if (!b) return null;
  const s = spendState(b);
  const pct = Math.min(100, s.pct ?? 0);
  return (
    <Section
      id="spend-line"
      title="Spend"
      aside={<a href={href('budget')}>{b.kill_switch ? 'Kill switch on' : 'Budget'} <ArrowRight size={14} aria-hidden="true" /></a>}
    >
      <div style={{ display: 'flex', alignItems: 'baseline', justifyContent: 'space-between', gap: 8 }}>
        <span className="h1 num">{formatCredits(b.committed)}</span>
        <span className="small muted num">of {formatCredits(b.cap)} · {b.month}</span>
      </div>
      <div
        className={`meter ${s.tone === 'ok' ? '' : s.tone}`}
        role="meter"
        aria-valuemin={0}
        aria-valuemax={b.cap}
        aria-valuenow={b.committed}
        aria-label={`Credits committed this month: ${b.committed} of ${b.cap}`}
      >
        <span className="fill" style={{ width: `${pct}%` }} />
        {b.cap > 0 && <span className="tick" style={{ left: '80%' }} title="80% warning line" />}
        {s.projectedPct != null && (
          <span className="proj" style={{ left: `${Math.min(99.5, s.projectedPct)}%` }} title={`Projected month-end ${formatCredits(s.projected)}`} />
        )}
      </div>
      <div className="meter-scale">
        <span>{s.pct == null ? '—' : `${Math.round(s.pct)}% used`}</span>
        <span className="proj-key" data-tone={s.projectedTone}>
          <i aria-hidden="true" /> projected {formatCredits(s.projected)}
        </span>
      </div>
      {b.kill_switch && (
        <p className="small" style={{ margin: 0, color: 'var(--red)' }}>
          Kill switch is on: no new clips are generated until you switch it off.
        </p>
      )}
    </Section>
  );
}

function AutopilotBlock({ channels }: { channels: Channel[] }) {
  const { backend, run, busy } = useStudio();
  if (!channels.length) return null;
  const bySlug = new Map<string, Channel[]>();
  for (const c of channels) bySlug.set(c.character_slug, [...(bySlug.get(c.character_slug) ?? []), c]);
  return (
    <Section id="autopilot" title="Posting autopilot" aside="unlocks after 6 approved posts">
      <div className="panel rows">
        {[...bySlug.entries()].map(([slug, list]) => (
          <div key={slug}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 8, padding: '10px 14px 0' }}>
              <Livery slug={slug} />
              <b style={{ fontSize: 14 }}>{characterName(slug)}</b>
            </div>
            {list
              .sort((a, b) => a.platform.localeCompare(b.platform))
              .map((c) => (
                <AutopilotSwitch
                  key={c.account_id}
                  compact
                  channel={c}
                  busy={busy.has(`mode-${c.account_id}`)}
                  onToggle={(mode) =>
                    run(
                      `mode-${c.account_id}`,
                      () => backend.setAccountMode(c.account_id, mode),
                      mode === 'auto' ? `Autopilot on for ${c.handle ?? platformName(c.platform)}` : `Autopilot off for ${c.handle ?? platformName(c.platform)}`,
                    )
                  }
                />
              ))}
          </div>
        ))}
      </div>
    </Section>
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
