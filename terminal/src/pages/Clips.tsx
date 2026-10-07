// Clips (terminal v2, owner 2026-10-07: "the terminal should be structured around the clips I download and put into a folder"; this
// replaces "In the works"). At the top the Add clips box (DropBox), then the long list: one row per clip he dropped, with its
// one-word status, the studio's ★ suggestion and the character menu, the price and Make it (DropsTable). The chips filter the list
// (All, Pick a character, Ready, Making, Done, Blocked or failed) over the list, newest drop first; the filter lives in the address (`#/clips?f=ready`), so
// Today's tiles and warnings link straight to it. A clip that is made moves on to Videos; the picks on their 8 steps are there too.
import { useCallback, useEffect, useState } from 'react';
import { DropBox } from '../components/DropBox';
import { DropsTable } from '../components/DropsTable';
import { Skeleton } from '../components/ui';
import {
  CLIP_FILTERS, CLIP_FILTER_EMPTY, clipFilterQuery, filterClips, newestFirst, parseClipFilter, type ClipFilter,
} from '../lib/clipstatus';
import { href, parseHash, useNow } from '../lib/hooks';
import { activeRoster } from '../lib/roster';
import { useStudio } from '../lib/store';
import { inTracker } from '../lib/tracker';

const readFilter = () => parseClipFilter(parseHash(window.location.hash).query);

/**
 * The filter chip that is on, bound to `?f=` of the address. A tap rewrites the address in place (replaceState: no history entry
 * per tap, the page keeps its scroll, any other query key stays); a link to `#/clips?f=…` while the page is open (Today's tiles,
 * the tab, a pasted address) fires hashchange and the chip follows. An unknown `f` is All.
 */
function useClipFilter(): [ClipFilter, (f: ClipFilter) => void] {
  const [filter, setFilter] = useState<ClipFilter>(readFilter);
  useEffect(() => {
    const on = () => setFilter(readFilter());
    window.addEventListener('hashchange', on);
    return () => window.removeEventListener('hashchange', on);
  }, []);
  const choose = useCallback((next: ClipFilter) => {
    setFilter(next);
    try {
      const { param, query } = parseHash(window.location.hash);
      const q = clipFilterQuery(query, next);
      window.history.replaceState(null, '', href('clips', param ?? undefined, Object.fromEntries(new URLSearchParams(q))));
    } catch {
      // the address could not be rewritten: the filter still works, it is just not in the link
    }
  }, []);
  return [filter, choose];
}

export function Clips() {
  const { data } = useStudio();
  const now = useNow(60_000);
  const [filter, setFilter] = useClipFilter();
  if (!data) {
    return (
      <div className="page stack" aria-busy="true">
        <Skeleton h={160} />
        <Skeleton h={300} />
      </div>
    );
  }
  const all = newestFirst(data.tracker.filter((r) => inTracker(r, now) && r.drop_card)); // newest first (spec B.2); the filters carry the grouping
  const rows = filterClips(all, filter);
  return (
    <div className="page stack">
      <div>
        <h1 className="h1">Clips</h1>
        <p className="small muted" style={{ margin: '6px 0 0' }}>
          The videos you saved to put our characters into: the studio checks each one for free and suggests who goes in, you can put
          any of them in. Pick the character, then Make it. A clip that is made moves on to Videos.
        </p>
      </div>
      <DropBox />
      <DropsTable
        rows={rows}
        summaryRows={all}
        roster={activeRoster(data.characters)}
        budget={data.budget}
        now={now}
        empty={CLIP_FILTER_EMPTY[filter]}
        toolbar={
          <div className="chips" role="group" aria-label="Show clips">
            {CLIP_FILTERS.map((o) => (
              <button key={o.id} type="button" className="chip" aria-pressed={filter === o.id} onClick={() => setFilter(o.id)}>
                {o.label}
              </button>
            ))}
          </div>
        }
      />
    </div>
  );
}
