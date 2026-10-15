// Totals for all videos (owner 2026-10-15), the strip at the top of Characters → "All videos": how many videos are posted for the
// current filter (character / platform) and the sum of their posts' latest views, likes, comments, shares and saves. A KPI row of
// stat tiles in the established `kv` grid: sentence-case label, the value compact, and under it how many posts the sum covers. A
// figure a post has not got is left out of its sum and never counted as 0; a figure no post has is a dash. Text in ink colours.
import { formatViews } from '../lib/format';
import { LIBRARY_LOAD_LIMIT, TOTAL_METRICS, type PostedTotals, type TotalMetric } from '../lib/totals';

const LABEL: Record<TotalMetric, string> = { views: 'Views', likes: 'Likes', comments: 'Comments', shares: 'Shares', saves: 'Saves' };

/** "4 of 5 posts" (the posts this figure covers of the posts counted), or "none measured". */
export function coverage(covers: number, posts: number): string {
  return covers === 0 ? 'none measured' : `${covers} of ${posts} ${posts === 1 ? 'post' : 'posts'}`;
}

/** The strip (no store): `scope` names the filter ("Franz, TikTok"); `capped`: the library holds only the newest clips, so say so. */
export function TotalsStrip({ totals, scope, capped = false }: { totals: PostedTotals; scope: string; capped?: boolean }) {
  return (
    <section className="totals" aria-label="Totals for the posted videos">
      <div className="chart-head">
        <h3 className="label" style={{ margin: 0 }}>Totals · {scope}</h3>
      </div>
      {totals.videos === 0 ? (
        <p className="small muted" style={{ margin: 0 }}>No posted videos for this filter yet.</p>
      ) : (
        <>
          <div className="kv totals-kv">
            <div>
              <span className="label">Videos posted</span>
              <span className="v">{totals.videos}</span>
              <span className="small muted">{totals.posts} {totals.posts === 1 ? 'post' : 'posts'}</span>
            </div>
            {TOTAL_METRICS.map((m) => {
              const t = totals.metrics[m];
              return (
                <div key={m}>
                  <span className="label">{LABEL[m]}</span>
                  <span className="v">{t.sum == null ? <span className="apd-none" aria-label="not measured">—</span> : formatViews(t.sum)}</span>
                  <span className="small muted">{coverage(t.covers, totals.posts)}</span>
                </div>
              );
            })}
          </div>
          <p className="small muted" style={{ margin: 0 }}>
            The latest reading of each posted video. A figure a post has not got is left out, never counted as 0.
            {capped ? ` Counts the newest ${LIBRARY_LOAD_LIMIT} clips.` : ''}
          </p>
        </>
      )}
    </section>
  );
}
