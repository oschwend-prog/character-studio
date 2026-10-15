// "Account per day" (owner 2026-10-15), on a character's page: the last 7 London days of his accounts' REACH beside the views his Reels
// gained, and Instagram's own 7-day total of the account's views (Stories included) with what his Reels gained in the same days.
// Verified live 2026-10-15: only reach is per day; views, likes, comments and replies are ONE total over the last 7 days. Postiz and
// Instagram give no numbers for a single Story, only these account figures (`studio metrics accounts`, every 6 hours). A table of
// exact numbers with one small sparkline of the account's reach per day (one series, one colour: his own, as on Today's views chart);
// the established classes of the glance table, nothing restyled. Text stays in ink colours; the series colour is only on the line.
// Beside the sparkline the stats: the account's views over the last 7 days (when it was read, what his Reels gained in the same days
// and the rest, then likes, comments and replies of the window) and the views of all his posts over all time (owner 2026-10-15; the
// latter from the library's latest reading of each posted post, a post with no views left out of the sum, and it says how many posts
// it covers).
import { useMemo } from 'react';
import { seriesColor } from '../lib/glance';
import { formatViews } from '../lib/format';
import { useNow } from '../lib/hooks';
import { accountPerDay, sparkSegments, type AccountLine, type AccountPerDayModel, type AccountWindowModel } from '../lib/accountday';
import { useStudio } from '../lib/store';
import { postedTotals, type MetricTotal } from '../lib/totals';
import type { Character } from '../lib/types';
import { coverage } from './TotalsStrip';
import { Section } from './ui';

const SPARK_W = 148;
const SPARK_H = 36;
const SPARK_PAD = 5; // room for the end marker (radius 4) and its ring

export const ACCOUNT_STORY_LINE =
  'Account views are Instagram’s total for the last 7 days, Stories included: Instagram and Postiz give no numbers for a single Story and no views per day.';
export const ACCOUNT_EMPTY =
  'No account numbers yet. The metrics job stores them every 6 hours once Postiz answers; the first reading shows here.';

// Reach is per day, as Instagram gives it; the Reels are the views his posts gained that day. The account's views are one 7-day figure
// (above the table), not a column.
const COLUMNS: ReadonlyArray<{ key: keyof AccountLine; label: string; title: string }> = [
  { key: 'reach', label: 'Reach', title: 'Accounts reached that day' },
  { key: 'reels', label: 'Reels', title: 'Views his Reels gained between our readings, counted on the day we read them' },
];

/** The views of all his posted posts over all time: the sum, how many posts have the figure, and how many posts are posted. */
export interface ReelsAllTime {
  views: MetricTotal;
  posts: number;
}

/** The store-connected block of one character: his accounts' handles, what the metrics job stored and his Reels' views per day. */
export function AccountPerDay({ character }: { character: Pick<Character, 'slug' | 'name' | 'accounts'> }) {
  const { data } = useStudio();
  const now = useNow(60_000);
  const model = useMemo(
    () => accountPerDay(character.slug, character.accounts.map((a) => a.handle), data?.accountDaily ?? [], data?.viewsDaily ?? [], now),
    [character.slug, character.accounts, data?.accountDaily, data?.viewsDaily, now],
  );
  const allTime = useMemo<ReelsAllTime | undefined>(() => {
    if (!data) return undefined;
    const t = postedTotals(data.library, { character: character.slug });
    return { views: t.metrics.views, posts: t.posts };
  }, [data, character.slug]);
  return <AccountPerDayCard name={character.name} slug={character.slug} model={model} allTime={allTime} />;
}

/** The block itself (no store). */
export function AccountPerDayCard({ name, slug, model, allTime }: { name: string; slug: string; model: AccountPerDayModel; allTime?: ReelsAllTime }) {
  const id = `artist-${slug}-account-day`;
  if (!model.hasData) {
    return (
      <Section title="Account per day" id={id}>
        <p className="small muted" style={{ margin: 0 }}>{ACCOUNT_EMPTY}</p>
        {allTime && <div className="apd-stats"><AllTimeStat allTime={allTime} /></div>}
      </Section>
    );
  }
  return (
    <Section title="Account per day" id={id} aside={<span className="num">added up: {model.counted.join(' · ')}</span>}>
      <Spark model={model} slug={slug} allTime={allTime} />
      <div className="panel ll-scroll" role="region" aria-label={`${name}: account per day, last 7 days`} tabIndex={0}>
        <table className="glance-table apd-table">
          <caption className="sr-only">
            {name}’s accounts per London day, the last 7 days: the reach of the accounts, then the views his Reels gained.
          </caption>
          <thead>
            <tr>
              <th scope="col"><span className="label">Day</span></th>
              {COLUMNS.map((c) => (
                <th key={c.key} scope="col" className="n" title={c.title}>
                  <span className="label">{c.label}</span>
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {model.rows.map((r) => (
              <tr key={r.day} className={r.today ? 'apd-today' : undefined}>
                <th scope="row" aria-current={r.today ? 'date' : undefined}>{r.label}</th>
                {COLUMNS.map((c) => (
                  <Cell key={c.key} value={r[c.key]} />
                ))}
              </tr>
            ))}
          </tbody>
          <tfoot>
            <tr>
              <th scope="row">7 days</th>
              <td className="n num">
                <span className="apd-none" title="Reach is not added across days: the same person can be reached on several days" aria-label="not added up">—</span>
              </td>
              <Cell value={model.reelsWeek} />
            </tr>
          </tfoot>
        </table>
      </div>
      <p className="small muted" style={{ margin: 0 }}>{ACCOUNT_STORY_LINE}</p>
      <p className="small muted" style={{ margin: 0 }}>
        Reach is per day. Reels counts the views his posts gained between our readings, on the day we read them; what is left of the account’s views after the Reels is Stories and older posts.
      </p>
    </Section>
  );
}

function Cell({ value }: { value: number | null }) {
  return (
    <td className="n num">
      {value == null ? <span className="apd-none" aria-label="no reading">—</span> : formatViews(value)}
    </td>
  );
}

/** The all-time figure as a stat: his posts' views summed over every posted post that has them, with how many posts that covers. */
function AllTimeStat({ allTime }: { allTime: ReelsAllTime }) {
  const { views, posts } = allTime;
  return (
    <div className="apd-stat">
      <span className="label">Reels views, all time</span>
      <span className="v">{views.sum == null ? <span className="apd-none" aria-label="not measured">—</span> : formatViews(views.sum)}</span>
      <span className="small muted">{posts === 0 ? 'no posted videos yet' : coverage(views.covers, posts)}</span>
    </div>
  );
}

/** "Likes 1 · Comments 2 · Replies 0": the window's smaller figures, the ones that were reported (a real 0 is shown, a missing one is not). */
export function windowSmallFigures(w: AccountWindowModel): string {
  return ([['Likes', w.likes], ['Comments', w.comments], ['Replies', w.replies]] as const)
    .flatMap(([label, n]) => (n == null ? [] : [`${label} ${formatViews(n)}`]))
    .join(' · ');
}

/** The account's views over the last 7 days: Instagram's one total (Stories included), when it was read, and, when both are known and
 * the rest is not below 0, what his Reels gained in the same days and what is left. Then the window's likes, comments and replies. */
function WindowStat({ window: w }: { window: AccountWindowModel | null }) {
  const small = w ? windowSmallFigures(w) : '';
  return (
    <div className="apd-stat">
      <span className="label">Account views, last 7 days</span>
      <span className="v">{w?.views == null ? <span className="apd-none" aria-label="not read">—</span> : formatViews(w.views)}</span>
      {w?.readAgo && <span className="small muted">read {w.readAgo}</span>}
      {w && w.reels != null && w.rest != null && (
        <span className="small muted">Reels gained {formatViews(w.reels)} in the same 7 days · rest {formatViews(w.rest)} (Stories, older posts)</span>
      )}
      {small && <span className="small muted">{small}</span>}
    </div>
  );
}

/** The account's reach per day: one line in his colour, 0 at the bottom, an 8 px marker (ringed in the panel colour) on the newest day,
 * and beside it the account's views of the last 7 days (with the Reels and the rest they are made of) and the all-time Reels views. */
function Spark({ model, slug, allTime }: { model: AccountPerDayModel; slug: string; allTime?: ReelsAllTime }) {
  const g = sparkSegments(model.reach, SPARK_W, SPARK_H, SPARK_PAD);
  const color = seriesColor(slug);
  const said = model.rows.flatMap((r) => (r.reach == null ? [] : [`${r.label} ${formatViews(r.reach)}`])).join(', ');
  return (
    <div className="apd-head">
      {g.segments.length > 0 && (
        <svg
          className="apd-spark" width={SPARK_W} height={SPARK_H} viewBox={`0 0 ${SPARK_W} ${SPARK_H}`} role="img"
          aria-label={`Account reach per day, last 7 days: ${said}`}
        >
          {g.segments.map((points, i) =>
            points.includes(' ') ? (
              <polyline key={i} points={points} fill="none" stroke={color} className="chart-line" />
            ) : (
              <circle key={i} cx={points.split(',')[0]} cy={points.split(',')[1]} r="2" fill={color} />
            ),
          )}
          {g.last && <circle cx={g.last.x} cy={g.last.y} r="4" fill={color} stroke="var(--panel)" strokeWidth="2" />}
        </svg>
      )}
      <div className="apd-stats">
        <WindowStat window={model.window} />
        {allTime && <AllTimeStat allTime={allTime} />}
      </div>
    </div>
  );
}
