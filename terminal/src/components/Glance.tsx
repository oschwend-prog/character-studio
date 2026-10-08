// "Studio at a glance" (terminal v3, spec 5.1), the first block of Today: one row per live character plus All. A table on a wide
// screen (the name column pinned, the table scrolls inside its own box), one card per character on a phone. A tap on a row opens
// that character's clips. Under it the views per day (one line per live character, 7 days, 30 days or all time) or, before any
// post was measured, what will appear there. overview.ts counts; lib/glance.ts says it in words; this file only draws.
import { Play } from 'lucide-react';
import { useMemo, useState } from 'react';
import { formatViews, londonDate, londonDayKey } from '../lib/format';
import {
  TEST_STATUS_TONE, chartGeometry, hitsLabel, lastWeekViews, nextPostLabel, runwayLabel, seriesColor, testStatusLabel,
} from '../lib/glance';
import { href } from '../lib/hooks';
import { VIEWS_EMPTY, VIEWS_PERIODS, overviewRows, viewsSeries, type OverviewRow, type ViewsPeriod, type ViewsSeries } from '../lib/overview';
import { nameOf } from '../lib/roster';
import { useStudio } from '../lib/store';
import { Avatar, Livery, Section } from './ui';

const clipsOf = (r: OverviewRow) => (r.slug ? href('clips', undefined, { c: r.slug }) : href('clips'));
const n = (x: number) => x.toLocaleString('en-GB');
const plural = (k: number, one: string, many: string) => (k === 1 ? one : many);

export function Glance({ now }: { now: number }) {
  const { data } = useStudio();
  const [period, setPeriod] = useState<ViewsPeriod>('30d');
  const rows = useMemo(() => (data ? overviewRows(data, now) : []), [data, now]);
  const slugs = useMemo(() => rows.filter((r) => r.slug).map((r) => r.slug!), [rows]);
  // the live characters only (a paused one keeps his history but has no line): Task 4 review
  const series = useMemo(() => viewsSeries(data?.viewsDaily ?? [], period, now, slugs), [data, period, now, slugs]);
  if (!data) return null;

  const live = rows.filter((r) => r.slug);
  const all = rows.find((r) => !r.slug) ?? null;
  const lastWeek = (r: OverviewRow) => lastWeekViews(data.viewsDaily ?? [], r.slug ? [r.slug] : slugs, now);
  const names = new Map(data.characters.map((c) => [c.slug, c.name]));

  return (
    <Section
      id="glance"
      title="Studio at a glance"
      aside={all ? <span className="num g-aside">{all.readyToMake} ready · {all.toApprove} to approve · {all.posted} posted</span> : undefined}
    >
      {live.length === 0 ? (
        <div className="panel empty">
          <b>No live character yet.</b>
          <span className="muted small">Each character gets a row here once his status is live (refs.json, then bin/studio seed).</span>
        </div>
      ) : (
        <>
          <ul className="glance-cards" aria-label="Studio at a glance, one card per character">
            {[...(all ? [all] : []), ...live].map((r) => (
              <GlanceCard key={r.slug ?? 'all'} row={r} lastWeek={lastWeek(r)} now={now} />
            ))}
          </ul>
          <GlanceTable rows={rows} lastWeek={lastWeek} now={now} />
          <details className="hint glance-key">
            <summary>What these numbers mean</summary>
            <p>
              Ready to make: checked clips with no Make it yet (some may first need your choice of character). Views: what his posts
              gained per London day (the stats pull runs daily), with last week next to the 7 days. Runway: how long his ready clips last
              at his posting days. Test status: his Instagram against the bar of the weekly review (not yet, on track, promote, at risk).
              Hits: the share of his measured videos at 3× his usual views or more.
            </p>
          </details>
        </>
      )}
      <ViewsChart series={series} period={period} onPeriod={setPeriod} now={now} names={names} />
    </Section>
  );
}

function ReadyCell({ r }: { r: OverviewRow }) {
  return (
    <>
      <b className="num">{r.readyToMake}</b>
      {r.needsYou > 0 && <span className="g-sub">{r.needsYou} {plural(r.needsYou, 'needs', 'need')} your choice</span>}
    </>
  );
}

function BestLink({ r, short = false }: { r: OverviewRow; short?: boolean }) {
  const b = r.bestThisWeek;
  if (!b) return <span className="faint">{short ? '—' : 'no post this week'}</span>;
  const hook = b.hook?.trim() || 'untitled video';
  return (
    <a
      className="g-best" href={href('characters', 'all', { clip: b.clipId })} title={`${hook} · ${n(b.views)} views`}
      aria-label={`Play ${r.slug ? '' : `${nameOf(b.slug)}’s `}best video this week: ${hook}, ${n(b.views)} views`}
      onClick={(e) => e.stopPropagation()}
    >
      <Play size={13} aria-hidden="true" />
      {!r.slug && !short && <span className="muted">{nameOf(b.slug)}</span>}
      <span className="g-best-hook">“{hook}”</span>
      <span className="num muted">{formatViews(b.views)}</span>
    </a>
  );
}

/** The 7 days figure with last week's next to it (a number always has a comparison). */
function WeekViews({ r, lastWeek }: { r: OverviewRow; lastWeek: number }) {
  if (!r.hasViews) return <span className="faint">—</span>;
  return (
    <>
      <b className="num">{formatViews(r.views7d)}</b>
      <span className="g-sub num">last week {formatViews(lastWeek)}</span>
    </>
  );
}

const views = (r: OverviewRow, v: number) => (r.hasViews ? formatViews(v) : '—');

function GlanceTable({ rows, lastWeek, now }: { rows: OverviewRow[]; lastWeek(r: OverviewRow): number; now: number }) {
  return (
    <div className="panel ll-scroll glance-wide" role="region" aria-label="Studio at a glance, per character" tabIndex={0}>
      <table className="glance-table">
        <caption className="sr-only">Each live character and all of them together: clips, views, follows, next post, runway, test status, hits.</caption>
        <thead>
          <tr>
            <th rowSpan={2} scope="col" className="g-name"><span className="label">Character</span></th>
            <th colSpan={5} scope="colgroup" className="g-group"><span className="label">Clips and videos</span></th>
            <th colSpan={4} scope="colgroup" className="g-group"><span className="label">Views</span></th>
            <th rowSpan={2} scope="col" className="n"><span className="label">Follows<br />7 days</span></th>
            <th rowSpan={2} scope="col"><span className="label">Next post</span></th>
            <th rowSpan={2} scope="col"><span className="label">Runway</span></th>
            <th rowSpan={2} scope="col"><span className="label">Test status</span></th>
            <th rowSpan={2} scope="col" className="n"><span className="label">Hits</span></th>
            <th rowSpan={2} scope="col"><span className="label">Best this week</span></th>
          </tr>
          <tr>
            <th scope="col" className="n"><span className="label">Ready to make</span></th>
            <th scope="col" className="n"><span className="label">Being made</span></th>
            <th scope="col" className="n"><span className="label">To approve</span></th>
            <th scope="col" className="n"><span className="label">Scheduled</span></th>
            <th scope="col" className="n"><span className="label">Posted</span></th>
            <th scope="col" className="n"><span className="label">Today</span></th>
            <th scope="col" className="n"><span className="label">7 days</span></th>
            <th scope="col" className="n"><span className="label">30 days</span></th>
            <th scope="col" className="n"><span className="label">All time</span></th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => {
            const to = clipsOf(r);
            const next = nextPostLabel(r.nextPost, now);
            return (
              <tr
                key={r.slug ?? 'all'} className={`g-row${r.slug ? '' : ' g-all'}`} data-char={r.slug ?? 'all'}
                onClick={(e) => {
                  if (!(e.target as HTMLElement).closest('a, button')) window.location.hash = to;
                }}
              >
                <th scope="row" className="g-name">
                  <a className="g-name-link" href={to} aria-label={r.slug ? `${r.name}’s clips` : 'All clips'}>
                    {r.slug ? <Livery slug={r.slug} /> : null}
                    <span>{r.slug ? r.name : 'All'}</span>
                  </a>
                </th>
                <td className="n"><ReadyCell r={r} /></td>
                <td className="n num">{r.beingMade}</td>
                <td className="n num">{r.toApprove}</td>
                <td className="n num">{r.scheduled}</td>
                <td className="n num">{r.posted}</td>
                <td className="n num">{views(r, r.viewsToday)}</td>
                <td className="n"><WeekViews r={r} lastWeek={lastWeek(r)} /></td>
                <td className="n num">{views(r, r.views30d)}</td>
                <td className="n num">{views(r, r.viewsAll)}</td>
                <td className="n num">{r.hasViews ? `+${n(r.follows7d)}` : '—'}</td>
                <td>
                  <span className="num">{next.when}</span>
                  <span className="g-sub">{next.note}</span>
                </td>
                <td>
                  <span>{runwayLabel(r.runwayWeeks)}</span>
                  {r.postsPerWeek != null && <span className="g-sub num">{r.postsPerWeek} {plural(r.postsPerWeek, 'post', 'posts')} a week</span>}
                </td>
                <td>{r.testStatus ? <span className={`tag g-test ${TEST_STATUS_TONE[r.testStatus]}`}>{testStatusLabel(r.testStatus)}</span> : <span className="faint">—</span>}</td>
                <td className="n num">{hitsLabel(r.hitRate)}</td>
                <td className="g-best-cell"><BestLink r={r} short /></td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}

function GlanceCard({ row: r, lastWeek, now }: { row: OverviewRow; lastWeek: number; now: number }) {
  const next = nextPostLabel(r.nextPost, now);
  return (
    <li className={`panel glance-card${r.slug ? '' : ' all'}`} data-char={r.slug ?? 'all'}>
      <div className="g-card-head">
        {r.slug ? <Avatar slug={r.slug} name={r.name} size={32} /> : null}
        <a className="g-card-name row-link" href={clipsOf(r)}>
          {r.slug ? r.name : 'All characters'}
        </a>
        {r.testStatus && <span className={`tag g-test ${TEST_STATUS_TONE[r.testStatus]}`}>{testStatusLabel(r.testStatus)}</span>}
      </div>
      <div className="kv g-kv">
        <div><span className="label">Ready to make</span><span className="v"><ReadyCell r={r} /></span></div>
        <div><span className="label">Being made</span><span className="v num">{r.beingMade}</span></div>
        <div><span className="label">To approve</span><span className="v num">{r.toApprove}</span></div>
        <div><span className="label">Scheduled</span><span className="v num">{r.scheduled}</span></div>
        <div><span className="label">Posted</span><span className="v num">{r.posted}</span></div>
        <div><span className="label">Follows 7 days</span><span className="v num">{r.hasViews ? `+${n(r.follows7d)}` : '—'}</span></div>
      </div>
      <div className="kv g-kv four" role="group" aria-label="Views">
        <span className="label g-kv-cap" aria-hidden="true">Views</span>
        <div><span className="label">Today</span><span className="v num">{views(r, r.viewsToday)}</span></div>
        <div><span className="label">7 days</span><span className="v"><WeekViews r={r} lastWeek={lastWeek} /></span></div>
        <div><span className="label">30 days</span><span className="v num">{views(r, r.views30d)}</span></div>
        <div><span className="label">All time</span><span className="v num">{views(r, r.viewsAll)}</span></div>
      </div>
      <dl className="g-lines">
        <div><dt>Next post</dt><dd><span className="num">{next.when}</span> <span className="muted">· {next.note}</span></dd></div>
        <div>
          <dt>Runway</dt>
          <dd>
            {runwayLabel(r.runwayWeeks)}
            {r.postsPerWeek != null && <span className="muted"> · {r.postsPerWeek} {plural(r.postsPerWeek, 'post', 'posts')} a week</span>}
          </dd>
        </div>
        <div><dt>Hits</dt><dd className="num">{hitsLabel(r.hitRate)}</dd></div>
        <div><dt>Best this week</dt><dd><BestLink r={r} /></dd></div>
      </dl>
    </li>
  );
}

const dayLabel = (day: string, today: string) => (day === today ? 'Today' : londonDate(Date.parse(`${day}T12:00:00Z`)));

function ViewsChart({
  series, period, onPeriod, now, names,
}: { series: ViewsSeries; period: ViewsPeriod; onPeriod(p: ViewsPeriod): void; now: number; names: ReadonlyMap<string, string> }) {
  const g = chartGeometry(series);
  const label = VIEWS_PERIODS.find((p) => p.id === period)?.label ?? '';
  const name = (slug: string) => names.get(slug) ?? nameOf(slug);
  const today = londonDayKey(now);
  const summary = `Views per day, ${label.toLowerCase()}: ${g.lines.map((l) => `${name(l.slug)} ${n(l.total)}`).join(', ')}`;
  return (
    <div className="views-chart">
      <div className="chart-head">
        <h3 className="label" style={{ margin: 0 }}>Views per day</h3>
        {series.hasViews && (
          <div className="seg" role="group" aria-label="Period">
            {VIEWS_PERIODS.map((p) => (
              <button key={p.id} type="button" aria-pressed={period === p.id} onClick={() => onPeriod(p.id)}>
                {p.label}
              </button>
            ))}
          </div>
        )}
      </div>
      {!series.hasViews ? (
        <p className="small muted" style={{ margin: 0 }}>{VIEWS_EMPTY}</p>
      ) : (
        <>
          <div className="chart-frame">
            <div className="chart-y num" aria-hidden="true">
              <span>{formatViews(g.max)}</span>
              <span>{formatViews(g.max / 2)}</span>
              <span>0</span>
            </div>
            <svg className="chart-svg" viewBox="0 0 100 100" preserveAspectRatio="none" role="img" aria-label={summary}>
              {[2, 50, 98].map((y) => (
                <line key={y} x1="0" x2="100" y1={y} y2={y} className="chart-grid" />
              ))}
              {g.lines.map((l) => (
                <polyline key={l.slug} points={l.points} fill="none" stroke={seriesColor(l.slug)} className="chart-line" />
              ))}
            </svg>
          </div>
          <div className="chart-x num" aria-hidden="true">
            <span>{series.days.length ? dayLabel(series.days[0], today) : ''}</span>
            <span>{series.days.length ? dayLabel(series.days[series.days.length - 1], today) : ''}</span>
          </div>
          <div className="legend">
            {g.lines.map((l) => (
              <span key={l.slug} className="num">
                <i style={{ background: seriesColor(l.slug) }} />
                {name(l.slug)} {formatViews(l.total)} {plural(l.total, 'view', 'views')}
              </span>
            ))}
          </div>
        </>
      )}
    </div>
  );
}
