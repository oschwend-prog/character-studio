// The cloud hits job on Clips › By character (terminal v3, spec section 10): "Hot right now" above the character sections (the
// general lane's top 10: hot whatever their topic, any character may take one) and, in each character's section, "Worth saving"
// (his top 5 new hits). A hit card: the thumbnail (the stored platform link, a neutral tile when it is missing or has expired), the
// caption, who posted it where, views, reach and when, one line why; Open (the post in a new tab, to watch it), Use this clip
// (add_drop of its link, then set_hit_status dropped: the cloud fetches that one post and checks it for free; on a general hit a
// small choice of the characters who could take it first) and Not for us (dismissed). Nothing here costs credits.
import { ExternalLink, Flame } from 'lucide-react';
import { useRef, useState, type RefObject } from 'react';
import { platformName } from '../lib/format';
import { fileHit, hitNumbers, hitTakers, hitTitle, hitWhy, hotNow, postLink, worthSaving, type FiledHit } from '../lib/hits';
import type { RosterEntry } from '../lib/roster';
import { useStudio } from '../lib/store';
import type { Hit } from '../lib/types';
import { PickThumb } from './PickThumb';
import { Spinner } from './ui';

/** When the daily pull runs (studio-hits.yml): said in every empty state. */
const NEXT_PULL = 'New hits arrive every morning at 06:30.';
/** On a phone "Hot right now" shows this many until "Show all" (the whole top 10 on a wide screen). */
const PHONE_SHOWN = 5;

/** The ids hidden on this screen: a hit filed whose mark was refused stays in v_hits, but must not be filed twice by a retry. */
function useHidden(): [ReadonlySet<string>, (id: string) => void] {
  const [hidden, setHidden] = useState<ReadonlySet<string>>(new Set());
  return [hidden, (id) => setHidden((s) => new Set(s).add(id))];
}

/** A list that takes the focus when one of its cards leaves it (used, or not for us): the focus never falls back to the page. */
function useListFocus(): [RefObject<HTMLOListElement | null>, () => void] {
  const list = useRef<HTMLOListElement>(null);
  return [list, () => window.setTimeout(() => list.current?.focus({ preventScroll: true }), 0)];
}

/** "Hot right now" (spec 10): the general lane's top 10, any character. */
export function HotRightNow({ now }: { now: number }) {
  const { data } = useStudio();
  const [hidden, hide] = useHidden();
  const [list, refocus] = useListFocus();
  const [all, setAll] = useState(false);
  const hot = hotNow((data?.hits ?? []).filter((h) => !hidden.has(h.hit_id)), 10);
  const characters = data?.characters ?? [];
  return (
    <section className="panel hot" aria-labelledby="hot-title">
      <div className="hot-head">
        <h2 className="h2" id="hot-title">
          <Flame size={15} aria-hidden="true" /> Hot right now
        </h2>
        <span className="small muted">Viral and rising on TikTok and Instagram this week: any character can take one.</span>
      </div>
      {hot.length === 0 ? (
        <p className="small muted hot-empty">Nothing hot right now. {NEXT_PULL}</p>
      ) : (
        <>
          <ol ref={list} tabIndex={-1} className={`hit-list hot-list${all ? ' all' : ''}`} aria-label="Hot right now, best first">
            {hot.map((h) => (
              <HitCard key={h.hit_id} hit={h} now={now} takers={hitTakers(h, characters)} onHide={hide} onGone={refocus} />
            ))}
          </ol>
          {hot.length > PHONE_SHOWN && !all && (
            <button type="button" className="btn ghost hot-more" onClick={() => setAll(true)}>
              Show all {hot.length}
            </button>
          )}
        </>
      )}
    </section>
  );
}

/**
 * His "Worth saving" (spec 10): his top 5 new hits, in a fold that is open when fewer than 3 of his clips are ready to make (he is
 * running low) and closed otherwise (his own clips come first); the summary says how many there are.
 */
export function WorthSaving({ slug, name, readyCount, now }: { slug: string; name: string; readyCount: number; now: number }) {
  const { data } = useStudio();
  const [hidden, hide] = useHidden();
  const [list, refocus] = useListFocus();
  const [open, setOpen] = useState(readyCount < 3);
  const hits = worthSaving((data?.hits ?? []).filter((h) => !hidden.has(h.hit_id)), slug, 5);
  const him: RosterEntry = { slug, name };
  return (
    <details className="worth" open={open} onToggle={(e) => setOpen(e.currentTarget.open)}>
      <summary>
        <span className="pick-group-head">Worth saving <span className="count">{hits.length}</span></span>
        <span className="small muted worth-sum">{hits.length ? `new ${hits.length === 1 ? 'hit' : 'hits'} for ${name}` : 'none yet'}</span>
      </summary>
      {hits.length === 0 ? (
        <p className="small muted worth-empty">No new hits for {name}. {NEXT_PULL}</p>
      ) : (
        <>
          <p className="hint worth-hint">
            His top new hits on TikTok and Instagram, best first. Use one and it is filed as his clip: fetched and checked for free.
          </p>
          <ol ref={list} tabIndex={-1} className="hit-list" aria-label={`Worth saving for ${name}, best first`}>
            {hits.map((h) => (
              <HitCard key={h.hit_id} hit={h} now={now} takers={[him]} forHim onHide={hide} onGone={refocus} />
            ))}
          </ol>
        </>
      )}
    </details>
  );
}

/**
 * One hit. `forHim`: Use this clip files it for the one character in `takers` at once; otherwise it opens a small choice of
 * `takers` (focus on Cancel: a mis-tap on a phone must not file a clip for the wrong character).
 */
function HitCard({
  hit: h, now, takers, forHim = false, onHide, onGone,
}: {
  hit: Hit;
  now: number;
  takers: ReadonlyArray<RosterEntry>;
  forHim?: boolean;
  /** Hide it on this screen (filed, but the mark was refused). */
  onHide(id: string): void;
  /** It leaves the list (used, or not for us): the list takes the focus. */
  onGone(): void;
}) {
  const { backend, run, toast, busy } = useStudio();
  const [choosing, setChoosing] = useState(false);
  const useButton = useRef<HTMLButtonElement>(null);
  const key = `hit-${h.hit_id}`;
  const working = busy.has(key);
  const title = hitTitle(h);
  const link = postLink(h.url);
  const where = platformName(h.platform);
  const choiceId = `hit-choice-${h.hit_id}`;

  const use = async ({ slug, name }: RosterEntry) => {
    let filed = null as FiledHit | null;
    const ok = await run(key, async () => {
      filed = await fileHit(backend, h, slug);
    });
    if (!ok || !filed) return; // refused: run showed the database's own words
    const r: FiledHit = filed;
    setChoosing(false);
    onGone();
    if (!r.marked) {
      onHide(h.hit_id);
      toast(`Filed for ${name}, but the hit is still listed as new: ${r.markError}`, 'error');
      return;
    }
    toast(r.duplicate ? `Already in ${name}’s clips: checked again (free)` : `Filed for ${name}: the clip is fetched and checked for free`);
  };
  const dismiss = async () => {
    if (await run(key, () => backend.setHitStatus(h.hit_id, 'dismissed'), 'Not for us: hidden')) onGone();
  };

  return (
    <li className="hit-item" data-lane={h.character_slug ?? 'general'}>
      <PickThumb
        pick={{ thumbnail_url: h.thumbnail_url, preview_url: null, platform: h.platform, creator_handle: h.creator_handle, hook: title, url: h.url }}
        size="small"
      />
      <div className="hit-main">
        <div className="hit-top">
          <span className="hit-title">{title}</span>
          <span className="rank-score num" title="How hot it is (0-100): views, reach against the creator’s followers, and freshness">
            <span className="sr-only">How hot: </span><b>{h.score}</b><span className="muted">/100</span>
          </span>
        </div>
        <span className="small muted hit-who">{h.creator_handle ? `${h.creator_handle} on ${where}` : where}</span>
        <span className="small num">{hitNumbers(h, now).join(' · ')}</span>
        <span className="small hit-why">{hitWhy(h, now)}</span>
      </div>
      <div className="hit-actions">
        {link && (
          <a className="btn ghost" href={link} target="_blank" rel="noopener noreferrer" aria-label={`Open ${title} on ${where} (a new tab)`}>
            Open <ExternalLink aria-hidden="true" />
          </a>
        )}
        <button
          ref={useButton} type="button" className="btn line" disabled={working || !takers.length || choosing} aria-busy={working && !choosing}
          aria-expanded={forHim ? undefined : choosing} aria-controls={forHim ? undefined : choiceId}
          onClick={() => (forHim ? void use(takers[0]) : setChoosing(true))}
        >
          {working && !choosing && <Spinner />} {forHim ? 'Use this clip' : 'Use this clip…'}
        </button>
        <button type="button" className="btn ghost" disabled={working} onClick={() => void dismiss()}>
          Not for us
        </button>
      </div>
      {!forHim && !takers.length && <p className="small muted hit-note">No live character can take it yet.</p>}
      {choosing && (
        <div className="hit-choice" id={choiceId} role="group" aria-labelledby={`${choiceId}-q`}>
          <span className="small" id={`${choiceId}-q`}>Who goes in? The clip is filed for him and checked for free.</span>
          <span className="hit-choice-buttons">
            {takers.map((t) => (
              <button key={t.slug} type="button" className="btn line" disabled={working} aria-busy={working} onClick={() => void use(t)}>
                {t.name}
              </button>
            ))}
            <button
              type="button" className="btn ghost" autoFocus disabled={working}
              onClick={() => {
                setChoosing(false);
                window.setTimeout(() => useButton.current?.focus(), 0); // back to the button that opened the choice
              }}
            >
              Cancel
            </button>
          </span>
          {working && (
            <span className="small muted" role="status">
              <Spinner /> Filing it…
            </span>
          )}
        </div>
      )}
    </li>
  );
}
