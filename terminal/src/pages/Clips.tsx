// New clips (terminal v2 "Clips", owner 2026-10-07: "the terminal should be structured around the clips I download and put into a
// folder"; v3 2026-10-07: "show per character what clips are a good choice ... rank them"; redesign 2026-10-15: "share source of
// clips on top - we have the folder plus social media scan ? then i should be able to view video on page and decide for which
// character and how to generate. after that the video moves to production stage ... call section also new clips or available
// clips as these are all pre generation ... a structured and easy to understand page"). Top to bottom: one line when Higgsfield is
// out of credits (lib/credits.ts); Sources (the clips folder, a link or videos added here, the daily social scan: Sources.tsx);
// Available clips, every clip not made yet under one filter kept in the address as `?c=` (All, Needs a character, one chip per live
// character; `#/clips?c=franz` opens on his), each card watchable with Who, How and ＋ Add (AvailableClips in RankedClips.tsx);
// the production line (what left for Videos › Making and what waits for his OK there); How the score works, folded; the Make bar
// (sticky once a clip is added). `#/clips?v=all` is All clips: every clip he dropped, made ones too, one card each (DropsTable),
// the chips filter it (All, Pick a character, Ready, Making, Done, Blocked or failed) and the filter lives in the address too
// (`#/clips?v=all&f=problems`; an address with only `f` is All clips as well).
import { ArrowLeft, ArrowRight, CircleAlert } from 'lucide-react';
import { useCallback, useEffect, useMemo, useState } from 'react';
import { DropsTable } from '../components/DropsTable';
import { MakeBar, useTicks } from '../components/MakeBar';
import { AvailableClips } from '../components/RankedClips';
import { Sources } from '../components/Sources';
import { Skeleton } from '../components/ui';
import {
  CLIP_FILTERS, CLIP_FILTER_EMPTY, clipChip, filterClips, newestFirst, parseClipFilter, type ClipFilter,
} from '../lib/clipstatus';
import { filterAddressQuery, parseClipsView } from '../lib/clipsview';
import { creditsOut } from '../lib/credits';
import { href, parseHash, useNow } from '../lib/hooks';
import { liveSelection } from '../lib/makebar';
import { parseAvailableFilter, productionCounts, type AvailableFilter } from '../lib/newclips';
import { activeRoster, orderRoster } from '../lib/roster';
import { useStudio } from '../lib/store';
import { inTracker } from '../lib/tracker';
import type { TrackerRow } from '../lib/types';

const readFilter = () => parseClipFilter(parseHash(window.location.hash).query);

/**
 * The filter chip that is on, bound to `?f=` of the address. A tap rewrites the address in place (replaceState: no history entry
 * per tap, the page keeps its scroll, any other query key stays, `v=all` is set: a filter exists only in All clips); a link to `#/clips?f=…` while the page is open (Today's tiles,
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
      const q = filterAddressQuery(query, next); // v=all too: a filter exists only in All clips
      window.history.replaceState(null, '', href('clips', param ?? undefined, Object.fromEntries(new URLSearchParams(q))));
    } catch {
      // the address could not be rewritten: the filter still works, it is just not in the link
    }
  }, []);
  return [filter, choose];
}

/** Scroll to the available clips, clear of the sticky top bar (measured: it grows with the phone's safe area). */
function scrollToList() {
  const el = document.getElementById('avail');
  if (!el) return;
  const above = document.querySelector('.topbar')?.getBoundingClientRect().height ?? 64;
  window.scrollTo({ top: Math.max(0, el.getBoundingClientRect().top + window.scrollY - above - 8) });
}

/** The view and the query of the address, followed on every hashchange (a link from Today, the back button). */
function useClipsAddress(): { view: ReturnType<typeof parseClipsView>; query: string } {
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
  // `#/clips?c=franz` (a row of the glance, "All of his clips"): the list opens on his filter, scrolled to
  useEffect(() => {
    if (focus && loaded) scrollToList();
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
  const credits = creditsOut(all, now);
  return (
    <div className="page stack">
      <div>
        <h1 className="h1">New clips</h1>
        <p className="small muted" style={{ margin: '6px 0 0' }}>
          Not made yet. Watch each one, pick who and how, then make it: it moves on to Videos.
        </p>
      </div>
      {credits && (
        <p className="credits-out" role="status">
          <CircleAlert size={16} aria-hidden="true" /> {credits.line}
        </p>
      )}
      {view === 'character' ? (
        <NewClips rows={all} now={now} focus={focus} creditsNote={credits ? 'Higgsfield is out of credits: a make fails until you top up.' : null} />
      ) : (
        <>
          <a className="link back-link" href={href('clips')}>
            <ArrowLeft size={14} aria-hidden="true" /> New clips
          </a>
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
        </>
      )}
    </div>
  );
}

/**
 * The New clips view: Sources, the available clips under their filter (bound to `?c=`: a tap rewrites the address in place, a
 * link while the page is open moves the filter), the production line, the score's rules folded, and the Make bar. Nothing is
 * ticked at first; a tick that is no longer Ready (made, removed, checked again) drops out of the bar by itself.
 */
function NewClips({ rows, now, focus, creditsNote }: {
  rows: ReadonlyArray<TrackerRow>;
  now: number;
  focus: string | null;
  creditsNote: string | null;
}) {
  const { data } = useStudio();
  const { ticked, toggle, untick, clear } = useTicks();
  const live = useMemo(() => orderRoster((data?.characters ?? []).filter((c) => c.status === 'live')), [data]);
  const slugs = live.map((c) => c.slug).join(',');
  const [filter, setFilter] = useState<AvailableFilter>(() => parseAvailableFilter(focus, slugs.split(',')));
  // the address moves the filter on every hashchange (the tab, a link, the back button), also after a chip rewrote it in place
  useEffect(() => {
    const on = () => setFilter(parseAvailableFilter(new URLSearchParams(parseHash(window.location.hash).query).get('c'), slugs.split(',')));
    window.addEventListener('hashchange', on);
    return () => window.removeEventListener('hashchange', on);
  }, [slugs]);
  const choose = (next: AvailableFilter) => {
    setFilter(next);
    try {
      window.history.replaceState(null, '', href('clips', undefined, next === 'all' ? {} : { c: next }));
    } catch {
      // the address could not be rewritten: the filter still works, it is just not in the link
    }
    if ((document.getElementById('avail')?.getBoundingClientRect().top ?? 0) < 0) scrollToList();
  };
  if (!data) return null;
  const makeable = new Set(rows.filter((r) => clipChip(r) === 'ready').map((r) => r.pick_id));
  const selected = liveSelection(ticked, makeable);
  const prod = productionCounts(rows);
  return (
    <div className="make-scope stack">
      <Sources rows={rows} characters={live} now={now} />
      <AvailableClips rows={rows} characters={live} filter={filter} onFilter={choose} ticked={ticked} onTick={toggle} now={now} />
      <div className="production-line">
        <span>
          <b>In production</b> <span className="num">{prod.making}</span> being made · <span className="num">{prod.toApprove}</span> to approve
        </span>
        <a className="link" href={href('videos')}>
          Videos <ArrowRight size={14} aria-hidden="true" />
        </a>
      </div>
      <a className="link quiet-link" href={href('clips', undefined, { v: 'all' })}>
        Every clip, made ones too <ArrowRight size={14} aria-hidden="true" />
      </a>
      <details className="worth how">
        <summary>
          <h2 className="pick-group-head">How the score works</h2>
        </summary>
        <p className="hint worth-hint">
          The score is the free check’s guess at how likely the clip gets views with him in it (0-100); the best three are Top picks.
          ＋ Add the ones to make: the total shows in the bar, and you confirm it before anything is spent. A clip nobody makes is
          deleted after a while (30 days for a hit, 60 for your own) unless you switch Keep on (under More).
        </p>
      </details>
      <MakeBar rows={rows} selected={selected} budget={data.budget} onSent={untick} onClear={clear} note={creditsNote} />
    </div>
  );
}
