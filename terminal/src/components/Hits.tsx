// The cloud hits job on Clips › By character (terminal v3, spec section 10): "Hot right now" above the character sections (the
// general lane's top 10: hot whatever their topic, any character may take one) and, in each character's section, "Worth saving"
// (his top 5 new hits). A hit card: the thumbnail (the stored platform link, a neutral tile when it is missing or has expired), the
// caption, who posted it where, views, reach and when, one line why, how hot it is (0-100); Open (the post in a new tab, to watch
// it), Use this clip (add_drop of its link, set_hit_status dropped, then request_job process: the cloud fetches that one post and
// checks it for free, starting now; on a general hit a small choice first: "Let the check choose", or a live character by name)
// and Not for us (dismissed, with Undo). A refusal shows on the card. Nothing here costs credits.
import { ExternalLink, Flame } from 'lucide-react';
import { useRef, useState, type RefObject } from 'react';
import { platformName } from '../lib/format';
import {
  HOT_LIMIT, WORTH_LIMIT, fileHit, filedLine, hitNumbers, hitTakers, hitTitle, hitWhy, hotNow, postLink, worthSaving, type FiledHit,
} from '../lib/hits';
import { nameOf, type RosterEntry } from '../lib/roster';
import { useStudio } from '../lib/store';
import type { Hit } from '../lib/types';
import { PickThumb } from './PickThumb';
import { Spinner } from './ui';

/** When new hits come (studio-hits.yml): said in every empty state. */
const NEXT_PULL = 'New hits arrive once the daily hits job runs (every morning).';
/** What the number on a hit card is: said where the cards are, so a phone (no hover title) has it too. */
const SCORE_LINE = 'The number: how hot it is now, 0-100.';
/** On a phone "Hot right now" shows this many until "Show all" (the whole top 10 on a wide screen). */
const PHONE_SHOWN = 5;

const message = (e: unknown) => (e instanceof Error ? e.message : String(e));

/** The ids hidden on this screen: a hit leaves its list at once when it is used or set aside (a quick second tap cannot file it
 * again before the reload), and comes back on Undo. */
function useHidden(): { hidden: ReadonlySet<string>; hide(id: string): void; unhide(id: string): void } {
  const [hidden, setHidden] = useState<ReadonlySet<string>>(new Set());
  return {
    hidden,
    hide: (id) => setHidden((s) => new Set(s).add(id)),
    unhide: (id) =>
      setHidden((s) => {
        const next = new Set(s);
        next.delete(id);
        return next;
      }),
  };
}

/** A list that takes the focus when one of its cards leaves it (used, or not for us): the focus never falls back to the page. */
function useListFocus(): [RefObject<HTMLOListElement | null>, () => void] {
  const list = useRef<HTMLOListElement>(null);
  return [list, () => window.setTimeout(() => list.current?.focus({ preventScroll: true }), 0)];
}

/** "Hot right now" (spec 10): the general lane's top 10, any character. */
export function HotRightNow({ now }: { now: number }) {
  const { data } = useStudio();
  const { hidden, hide, unhide } = useHidden();
  const [list, refocus] = useListFocus();
  const [all, setAll] = useState(false);
  const hot = hotNow((data?.hits ?? []).filter((h) => !hidden.has(h.hit_id)), HOT_LIMIT);
  const takers = hitTakers(data?.characters ?? []);
  return (
    <section className="panel hot" aria-labelledby="hot-title">
      <div className="hot-head">
        <h2 className="h2" id="hot-title">
          <Flame size={15} aria-hidden="true" /> Hot right now
        </h2>
        <span className="small muted">
          Viral and rising on TikTok and Instagram this week: any character can take one. {SCORE_LINE}
        </span>
      </div>
      {hot.length === 0 ? (
        <p className="small muted hot-empty">Nothing hot right now. {NEXT_PULL}</p>
      ) : (
        <>
          <ol ref={list} tabIndex={-1} className={`hit-list hot-list${all ? ' all' : ''}`} aria-label="Hot right now, best first">
            {hot.map((h) => (
              <HitCard key={h.hit_id} hit={h} now={now} takers={takers} onHide={hide} onUnhide={unhide} onGone={refocus} />
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
 * running low) and closed otherwise (his own clips come first); the summary, a group head like his others, says how many.
 */
export function WorthSaving({ slug, name, readyCount, now }: { slug: string; name: string; readyCount: number; now: number }) {
  const { data } = useStudio();
  const { hidden, hide, unhide } = useHidden();
  const [list, refocus] = useListFocus();
  const [open, setOpen] = useState(readyCount < 3);
  const hits = worthSaving((data?.hits ?? []).filter((h) => !hidden.has(h.hit_id)), slug, WORTH_LIMIT);
  const him: RosterEntry = { slug, name };
  return (
    <details className="worth" open={open} onToggle={(e) => setOpen(e.currentTarget.open)}>
      <summary>
        <h3 className="pick-group-head">Worth saving <span className="count">{hits.length}</span></h3>
        <span className="small muted worth-sum">{hits.length ? `new ${hits.length === 1 ? 'hit' : 'hits'} for ${name}` : 'none yet'}</span>
      </summary>
      {hits.length === 0 ? (
        <p className="small muted worth-empty">No new hits for {name}. {NEXT_PULL}</p>
      ) : (
        <>
          <p className="hint worth-hint">
            His top new hits on TikTok and Instagram, best first. {SCORE_LINE} Use one and it is filed as his clip and checked for free.
          </p>
          <ol ref={list} tabIndex={-1} className="hit-list" aria-label={`Worth saving for ${name}, best first`}>
            {hits.map((h) => (
              <HitCard key={h.hit_id} hit={h} now={now} takers={[him]} forHim onHide={hide} onUnhide={unhide} onGone={refocus} />
            ))}
          </ol>
        </>
      )}
    </details>
  );
}

/**
 * One hit. `forHim`: Use this clip files it for the one character in `takers` at once. Otherwise it opens a small choice: "★ Let
 * the check choose" first (no character: the free check moves it to the one who fits), then `takers` by name (the owner's own
 * choice); the focus lands on Cancel (a mis-tap on a phone must not file a clip). A refusal stays on the card (role alert).
 */
function HitCard({
  hit: h, now, takers, forHim = false, onHide, onUnhide, onGone,
}: {
  hit: Hit;
  now: number;
  takers: ReadonlyArray<RosterEntry>;
  forHim?: boolean;
  /** Hide it on this screen at once (used, or not for us). */
  onHide(id: string): void;
  /** Show it again (Undo of Not for us). */
  onUnhide(id: string): void;
  /** It left the list: the list takes the focus. */
  onGone(): void;
}) {
  const { data, backend, run, toast, busy } = useStudio();
  const [choosing, setChoosing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const useButton = useRef<HTMLButtonElement>(null);
  const key = `hit-${h.hit_id}`;
  const working = busy.has(key);
  const title = hitTitle(h);
  const link = postLink(h.url);
  const where = platformName(h.platform);
  const choiceId = `hit-choice-${h.hit_id}`;
  const errorId = `hit-error-${h.hit_id}`;
  const names = new Map((data?.characters ?? []).map((c) => [c.slug, c.name]));

  /** Runs an owner action under the card's key: a refusal is kept for the card, never a toast; the data reloads either way. */
  const act = async (action: () => Promise<void>): Promise<boolean> => {
    setError(null);
    let refused: string | null = null;
    await run(key, async () => {
      try {
        await action();
      } catch (e) {
        refused = message(e);
      }
    });
    if (refused) setError(refused);
    return refused == null;
  };

  /** Use this clip: for `slug`, or (null) for the free check to choose. */
  const use = async (slug: string | null, name: string | null) => {
    let filed = null as FiledHit | null;
    if (!(await act(async () => void (filed = await fileHit(backend, h, slug)))) || !filed) return;
    setChoosing(false);
    onHide(h.hit_id);
    onGone();
    const line = filedLine(filed, name, (s) => names.get(s) ?? nameOf(s));
    toast(line.text, line.kind);
  };

  const dismiss = async () => {
    if (!(await act(() => backend.setHitStatus(h.hit_id, 'dismissed')))) return;
    onHide(h.hit_id);
    onGone();
    toast('Not for us: hidden', 'ok', {
      label: 'Undo',
      run: () => {
        onUnhide(h.hit_id);
        void run(key, () => backend.setHitStatus(h.hit_id, 'new'), 'Back in the list');
      },
    });
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
          <span className="rank-score num" title="How hot it is now (0-100): views, reach against the creator’s followers, and freshness">
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
          ref={useButton} type="button" className="btn line" disabled={working || choosing} aria-busy={working && !choosing}
          aria-expanded={forHim ? undefined : choosing} aria-controls={forHim ? undefined : choiceId}
          aria-describedby={error ? errorId : undefined}
          onClick={() => (forHim ? void use(takers[0]?.slug ?? null, takers[0]?.name ?? null) : (setError(null), setChoosing(true)))}
        >
          {working && !choosing && <Spinner />} {forHim ? 'Use this clip' : 'Use this clip…'}
        </button>
        <button type="button" className="btn ghost" disabled={working} onClick={() => void dismiss()}>
          Not for us
        </button>
      </div>
      {choosing && (
        <div className="hit-choice" id={choiceId} role="group" aria-labelledby={`${choiceId}-q`}>
          <span className="small" id={`${choiceId}-q`}>
            Who goes in? The check looks at the clip and picks the one who fits, or choose him yourself. Free either way.
          </span>
          <span className="hit-choice-buttons">
            <button type="button" className="btn line" disabled={working} aria-busy={working} onClick={() => void use(null, null)}>
              ★ Let the check choose
            </button>
            {takers.map((t) => (
              <button key={t.slug} type="button" className="btn line" disabled={working} aria-busy={working} onClick={() => void use(t.slug, t.name)}>
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
      {error && (
        <p className="error-text hit-error" id={errorId} role="alert">
          {error}
        </p>
      )}
    </li>
  );
}
