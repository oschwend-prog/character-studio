// Clips (terminal v2, owner 2026-10-07: "the terminal should be structured around the clips I download and put into a folder"; this
// replaces "In the works"; v3 2026-10-07: "show per character what clips are a good choice ... rank them"; redesign 2026-10-15:
// "too long, my clips buried, too many buttons and text": his clips first, one line of intro, the rest folded). At the top one
// line when Higgsfield is out of credits (lib/credits.ts), the Add clips box (DropBox), then one of two views, kept in the address.
// By character (the default, `#/clips`, `#/clips?c=franz` opens on his section): a sticky row of jump chips (one per live
// character: what needs him, else how many are ready), a section per live character, Needs you first, his Ready clips ranked by
// score as cards to watch, with the Add toggle and the Make bar, his "Worth saving" hits, then what is on its way and done in a
// fold (RankedClips); under them "Hot right now" (the cloud hits job's general lane, Hits.tsx) and "How the score works", both
// closed folds. All clips (`#/clips?v=all`): every clip he dropped, one card each (ClipCard, Task 11), with its
// one-word status, the studio's ★ suggestion and the character menu, the price and Make it (DropsTable); the chips filter it (All,
// Pick a character, Ready, Making, Done, Blocked or failed), newest drop first, and the filter lives in the address too
// (`#/clips?v=all&f=problems`; an address with only `f` is All clips as well). A clip that is made moves on to Videos.
import { CircleAlert } from 'lucide-react';
import { useCallback, useEffect, useMemo, useState } from 'react';
import { DropBox } from '../components/DropBox';
import { DropsTable } from '../components/DropsTable';
import { HotRightNow } from '../components/Hits';
import { MakeBar, useTicks } from '../components/MakeBar';
import { RankedClips, useRankOrder } from '../components/RankedClips';
import { ViewSwitch } from '../components/ViewSwitch';
import { Skeleton } from '../components/ui';
import {
  CLIP_FILTERS, CLIP_FILTER_EMPTY, clipChip, filterClips, newestFirst, parseClipFilter, type ClipFilter,
} from '../lib/clipstatus';
import { clipsByCharacter, clipsViewQuery, filterAddressQuery, jumpCount, parseClipsView, type ClipsView } from '../lib/clipsview';
import { creditsOut } from '../lib/credits';
import { href, parseHash, useNow } from '../lib/hooks';
import { liveSelection } from '../lib/makebar';
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

const VIEWS: ReadonlyArray<{ id: ClipsView; label: string }> = [
  { id: 'character', label: 'By character' },
  { id: 'all', label: 'All clips' },
];
/** Scroll to a character's section, clear of the sticky top bar and the jump chips (both measured: the top bar grows with the
 * phone's safe area). */
function scrollToSection(slug: string) {
  const el = document.getElementById(`clips-${slug}`);
  if (!el) return;
  const above = (document.querySelector('.topbar')?.getBoundingClientRect().height ?? 64)
    + (document.querySelector('.char-jump')?.getBoundingClientRect().height ?? 0);
  window.scrollTo({ top: Math.max(0, el.getBoundingClientRect().top + window.scrollY - above - 8) });
}

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
    if (focus && loaded) scrollToSection(focus);
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
        <h1 className="h1">Clips</h1>
        <p className="small muted" style={{ margin: '6px 0 0' }}>
          Your saved videos, checked for free and ranked per character. ＋ Add the best, then make them.
        </p>
      </div>
      {credits && (
        <p className="credits-out" role="status">
          <CircleAlert size={16} aria-hidden="true" /> {credits.line}
        </p>
      )}
      <DropBox />
      <ViewSwitch
        label="Show the clips"
        value={view}
        options={VIEWS}
        // the address at the moment of the tap (a filter chip rewrites it without a hashchange)
        to={(id) => href('clips', undefined, Object.fromEntries(new URLSearchParams(clipsViewQuery(parseHash(window.location.hash).query, id))))}
      />
      {view === 'character' ? (
        <ByCharacter rows={all} now={now} creditsNote={credits ? 'Higgsfield is out of credits: a make fails until you top up.' : null} />
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
 * By character (spec 6): the jump chips, a section per live character with his clips ranked and his "Worth saving" hits, then
 * "Hot right now" (spec 10: the general lane's top 10 hits, any character) and the score's rules folded, and the Make bar. Nothing is ticked at first; a tick that
 * is no longer Ready (made, removed, checked again) drops out of the bar by itself.
 */
function ByCharacter({ rows, now, creditsNote }: { rows: ReadonlyArray<TrackerRow>; now: number; creditsNote: string | null }) {
  const { data } = useStudio();
  const { ticked, toggle, untick, clear } = useTicks();
  const order = useRankOrder();
  const live = useMemo(() => orderRoster((data?.characters ?? []).filter((c) => c.status === 'live')), [data]);
  if (!data) return null;
  const makeable = new Set(rows.filter((r) => clipChip(r) === 'ready').map((r) => r.pick_id));
  const selected = liveSelection(ticked, makeable);
  const { groups } = clipsByCharacter(rows, live, order);
  return (
    <div className="make-scope stack">
      {groups.length > 1 && (
        <nav className="char-jump" aria-label="Jump to a character">
          {groups.map((g) => {
            const count = jumpCount(g);
            return (
              <button key={g.slug} type="button" className={`chip ${g.slug}`} onClick={() => scrollToSection(g.slug)}>
                {g.name} <span className={`num jump-count${count.needsYou ? ' jump-needs' : ''}`}>{count.text}</span>
              </button>
            );
          })}
        </nav>
      )}
      <RankedClips rows={rows} characters={live} ticked={ticked} onTick={toggle} now={now} />
      <HotRightNow now={now} />
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
