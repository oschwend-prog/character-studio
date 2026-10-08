// Clips (terminal v2, owner 2026-10-07: "the terminal should be structured around the clips I download and put into a folder"; this
// replaces "In the works"; v3 2026-10-07: "show per character what clips are a good choice ... rank them"). At the top the Add clips
// box (DropBox), then one of two views, kept in the address. By character (the default, `#/clips`, `#/clips?c=franz` opens on his
// section): a section per live character, Needs you first, his Ready clips ranked by score with tick boxes and the Make bar, then
// what is on its way and done (RankedClips). All clips (`#/clips?v=all`): the long list, one row per clip he dropped, with its
// one-word status, the studio's ★ suggestion and the character menu, the price and Make it (DropsTable); the chips filter it (All,
// Pick a character, Ready, Making, Done, Blocked or failed), newest drop first, and the filter lives in the address too
// (`#/clips?v=all&f=problems`; an address with only `f` is All clips as well). A clip that is made moves on to Videos.
import { useCallback, useEffect, useMemo, useState } from 'react';
import { DropBox } from '../components/DropBox';
import { DropsTable } from '../components/DropsTable';
import { MakeBar, useTicks } from '../components/MakeBar';
import { RankedClips } from '../components/RankedClips';
import { ViewSwitch } from '../components/ViewSwitch';
import { Skeleton } from '../components/ui';
import {
  CLIP_FILTERS, CLIP_FILTER_EMPTY, clipChip, clipFilterQuery, filterClips, newestFirst, parseClipFilter, type ClipFilter,
} from '../lib/clipstatus';
import { clipsViewQuery, parseClipsView, type ClipsView } from '../lib/clipsview';
import { href, parseHash, useNow } from '../lib/hooks';
import { liveSelection } from '../lib/makebar';
import { activeRoster, orderRoster } from '../lib/roster';
import { useStudio } from '../lib/store';
import { inTracker } from '../lib/tracker';
import type { TrackerRow } from '../lib/types';

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

const VIEWS: ReadonlyArray<{ id: ClipsView; label: string }> = [
  { id: 'character', label: 'By character' },
  { id: 'all', label: 'All clips' },
];
/** The sticky top bar's height, kept clear when the page opens on one character's section. */
const TOPBAR = 64;

/** The view and the query of the address, followed on every hashchange (the switch, a link from Today, the back button). */
function useClipsAddress(): { view: ClipsView; query: string } {
  const read = () => parseHash(window.location.hash).query;
  const [query, setQuery] = useState(read);
  useEffect(() => {
    const on = () => setQuery(read());
    window.addEventListener('hashchange', on);
    return () => window.removeEventListener('hashchange', on);
  }, []);
  return { view: parseClipsView(query), query };
}

export function Clips() {
  const { data } = useStudio();
  const now = useNow(60_000);
  const [filter, setFilter] = useClipFilter();
  const { view, query } = useClipsAddress();
  const focus = view === 'character' ? new URLSearchParams(query).get('c') : null;
  const loaded = data != null;
  // `#/clips?c=franz` (a row of the glance, "All of his clips"): the page opens on his section
  useEffect(() => {
    if (!focus || !loaded) return;
    const el = document.getElementById(`clips-${focus}`);
    if (el) window.scrollTo({ top: Math.max(0, el.getBoundingClientRect().top + window.scrollY - TOPBAR - 8) });
  }, [focus, loaded]);
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
          The videos you saved to put our characters into: the studio checks each one for free, scores it and suggests who goes in, you
          can put any of them in. Tick the best ones and make them. A clip that is made moves on to Videos.
        </p>
      </div>
      <DropBox />
      <ViewSwitch
        label="Show the clips"
        value={view}
        options={VIEWS}
        to={(id) => href('clips', undefined, Object.fromEntries(new URLSearchParams(clipsViewQuery(query, id))))}
      />
      {view === 'character' ? (
        <ByCharacter rows={all} now={now} />
      ) : (
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
      )}
    </div>
  );
}

/**
 * By character (spec 6): a section per live character with his clips ranked, and the Make bar under them. Nothing is ticked at
 * first; a tick that is no longer Ready (made, removed, checked again) drops out of the bar by itself.
 */
function ByCharacter({ rows, now }: { rows: ReadonlyArray<TrackerRow>; now: number }) {
  const { data } = useStudio();
  const { ticked, toggle, untick, clear } = useTicks();
  const live = useMemo(() => orderRoster((data?.characters ?? []).filter((c) => c.status === 'live')), [data]);
  if (!data) return null;
  const makeable = new Set(rows.filter((r) => clipChip(r) === 'ready').map((r) => r.pick_id));
  const selected = liveSelection(ticked, makeable);
  return (
    <div className="make-scope stack">
      <p className="hint" style={{ margin: 0 }}>
        Score: the free check’s guess at how likely the clip gets views with him in it (0-100); the best three are Top picks. Tick the
        ones to make: the total shows in the bar and you confirm it before anything is spent.
      </p>
      <RankedClips rows={rows} characters={live} ticked={ticked} onTick={toggle} now={now} />
      <MakeBar rows={rows} selected={selected} budget={data.budget} onSent={untick} onClear={clear} />
    </div>
  );
}
