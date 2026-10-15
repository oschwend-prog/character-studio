// Clip cards you can see and watch (terminal v3 Task 11, owner 2026-10-08: "make them larger so I can actually see them, maybe it's
// cards. Even better if I could click and watch them"; "this needs to be super user friendly and easy to produce"). A grid of big
// 9:16 cards (two columns on a phone): the picture on top (the check's cover, else the middle frame of its strip, else the pick's own
// thumbnail or tile) with the rank and Top pick top-left, the score top-right and a big play button; under it the title, the reason,
// the price and section, the character; then ONE full-width action (the Make toggle, the character menu, the chip, or a hit's Use
// this clip) and the small controls under it. A tap on the picture opens the player sheet (ClipPlayerSheet): the section with its
// own sound, the same facts and the same action (changing it there changes the card), Open the original and Close. A clip with no
// file of ours opens its post on TikTok, Instagram or YouTube in a new tab instead ("Watch on TikTok ↗"); with nothing to play the
// card has no play button. What plays is lib/clipcard.ts's playableFor.
import { ExternalLink, Play } from 'lucide-react';
import { useEffect, useId, useMemo, useRef, useState, type ReactNode, type Ref, type SyntheticEvent } from 'react';
import {
  MAKE_TOGGLE, afterPictureError, originalLink, pictureSources, removeStep, shouldLoopBack, withFragment, type PicturePos, type Playable,
  type PlayableSource, type RemoveStep,
} from '../lib/clipcard';
import { EXPLORE_HELP, EXPLORE_LABEL } from '../lib/ranking';
import { thumbFor } from '../lib/rules';
import { useStudio } from '../lib/store';
import type { DropCard } from '../lib/types';
import { scoreNote, scoreTestOf, type ScoreNote } from '../lib/weekly';
import { Sheet } from './ui';

type ThumbPick = Parameters<typeof thumbFor>[0];

/** The picture of a card: its files in sources/owner/ best first (lib/clipcard pictureSources), then the pick's own thumbnail. */
export interface CardPictureSpec {
  sources: ReadonlyArray<{ kind: 'cover' | 'strip'; path: string }>;
  thumb: ThumbPick;
}

/** Where an action is drawn: on the card, or in the player sheet (its ids must differ: both are in the page while it is open). */
export interface ActionPlace {
  where: 'card' | 'sheet';
  /** The ids of the title and the price where it is drawn: an action's aria-describedby. */
  describedBy: string;
}

/** The picture and play rule of a dropped clip (a v_tracker row). */
export function dropPicture(row: PlayableSource & ThumbPick & { drop_card?: DropCard | null }, title: string): CardPictureSpec {
  return {
    sources: pictureSources(row.drop_card),
    // a Genjutsu preview_url never plays inside the card's own button (the player is the card's): the still only
    thumb: { thumbnail_url: row.thumbnail_url, preview_url: null, platform: row.platform, creator_handle: row.creator_handle, hook: title, url: row.url },
  };
}

/**
 * The score test's caution (learning plan 3.2, test A): what the latest weekly review says about the score, as a small label.
 * Null once the test validated the score. Before the first review it is "unproven" (the score may steer nothing, an unvalidated one
 * must not look like a promise).
 */
export function useScoreNote(): ScoreNote | null {
  const { data } = useStudio();
  const weekly = data?.weekly;
  return useMemo(() => scoreNote(scoreTestOf(weekly)), [weekly]);
}

/** Whether the score test's label stands beside this score: only the free check's own score, and only when there is one (a hit's
 * "How hot" and every other figure is not what test A judges). Card and player sheet share this one rule. */
export const showsScoreCaution = (score: number | null | undefined, checkScore: boolean | undefined): boolean => checkScore === true && score != null;

/** The label beside a score: small, muted, the reason in its title and, for a screen reader, after it. */
export function ScoreCaution({ note, className }: { note: ScoreNote | null; className: string }) {
  if (!note) return null;
  return (
    <span className={className} title={note.title}>
      {note.text}
      <span className="sr-only">. {note.title}</span>
    </span>
  );
}

/** The cards: a list (phone: 2 columns; wider: as many 190 px columns as fit). */
export function ClipGrid({ label, className, children, listRef }: {
  label: string;
  className?: string;
  children: ReactNode;
  listRef?: Ref<HTMLUListElement>;
}) {
  return (
    <ul ref={listRef} tabIndex={listRef ? -1 : undefined} className={className ? `clip-grid ${className}` : 'clip-grid'} aria-label={label}>
      {children}
    </ul>
  );
}

export interface ClipCardProps {
  /** Unique on the page: the pick or hit id, with a prefix where the same clip can show twice (Today and Clips never share a page). */
  id: string;
  title: string;
  picture: CardPictureSpec;
  playable: Playable;
  /** #1, #2 ... (ranked lists only). */
  rank?: number | null;
  top?: boolean;
  /** An Explore clip (learning test A): one suggested clip in four comes from below his median score. Shown as a label with its help. */
  explore?: boolean;
  /** 0-100; null = "not scored yet"; undefined = no score on this card. */
  score?: number | null;
  /** What the score is (said to a screen reader before it, and as its hover title). */
  scoreLabel?: string;
  scoreTitle?: string;
  /**
   * The score is the free check's (the drop's score total), the one score test A judges: only then does the score test's label
   * ("unproven") stand beside it. A hit's "How hot" or any other figure never carries it. Default false.
   */
  checkScore?: boolean;
  reason?: ReactNode;
  /** "about 102 credits · 9 s". */
  price?: ReactNode;
  /** The player sheet's fuller price line ("about 102 credits · 1.5–10.5 s (9 s)"); `price` when absent. */
  sheetPrice?: ReactNode;
  character?: string | null;
  /** Lines after the price (who posted it, the versions, the star). */
  extra?: ReactNode;
  /** The one main action, drawn on the card and again in the player sheet. */
  action?: (place: ActionPlace) => ReactNode;
  /** Small controls under the action, always visible (a hit's Not for us, Open). */
  links?: ReactNode;
  /** More controls, folded under "More" (Keep, Use for another character, the details). */
  more?: ReactNode;
  /** An https link to the original post: "Open the original ↗" in the player sheet. */
  original?: string | null;
  ticked?: boolean;
  dataChar?: string | null;
  className?: string;
}

export function ClipCard(p: ClipCardProps) {
  const [watching, setWatching] = useState(false);
  const caution = useScoreNote();
  const [moreOpen, setMoreOpen] = useState(false);
  const base = `cc-${p.id}`;
  const titleId = `${base}-title`;
  const priceId = `${base}-price`;
  const describedBy = p.price ? `${titleId} ${priceId}` : titleId;
  return (
    <li
      className={['clip-card', p.className].filter(Boolean).join(' ')}
      data-char={p.dataChar ?? undefined}
      data-ticked={p.ticked === undefined ? undefined : p.ticked}
    >
      <div className="cc-media">
        <Badges rank={p.rank} top={p.top} score={p.score} scoreLabel={p.scoreLabel} scoreTitle={p.scoreTitle} />
        <CardMedia playable={p.playable} title={p.title} onWatch={() => setWatching(true)}>
          <CardPicture picture={p.picture} title={p.title} />
        </CardMedia>
      </div>
      <div className="cc-body">
        {p.explore && (
          <span className="small cc-explore">
            <span className="tag" title={EXPLORE_HELP}>{EXPLORE_LABEL}</span>
            <span className="muted">below his median score</span>
            <span className="sr-only">. {EXPLORE_HELP}</span>
          </span>
        )}
        <span className="cc-title" id={titleId}>{p.title}</span>
        {showsScoreCaution(p.score, p.checkScore) && <ScoreCaution note={caution} className="small cc-score-note" />}
        {p.reason && <span className="small muted cc-reason">{p.reason}</span>}
        {p.price && <span className="small num cc-price" id={priceId}>{p.price}</span>}
        {p.character && <span className="small cc-char">{p.character}</span>}
        {p.extra}
        {p.action && <div className="cc-action">{p.action({ where: 'card', describedBy })}</div>}
        {p.links && <div className="cc-links">{p.links}</div>}
        {p.more && (
          <details className="cc-more" open={moreOpen} onToggle={(e) => setMoreOpen(e.currentTarget.open)}>
            <summary>More <span aria-hidden="true">⋯</span></summary>
            {/* drawn when opened: a closed card signs no strip and asks nothing */}
            {moreOpen && <div className="cc-more-in">{p.more}</div>}
          </details>
        )}
      </div>
      {watching && p.playable.kind === 'file' && (
        <ClipPlayerSheet
          id={base} title={p.title} playable={p.playable} picture={p.picture} score={p.score} scoreLabel={p.scoreLabel} checkScore={p.checkScore} reason={p.reason}
          price={p.sheetPrice ?? p.price} character={p.character} action={p.action} original={p.original ?? null} onClose={() => setWatching(false)}
        />
      )}
    </li>
  );
}

function Badges({ rank, top, score, scoreLabel = 'Score', scoreTitle }: Pick<ClipCardProps, 'rank' | 'top' | 'score' | 'scoreLabel' | 'scoreTitle'>) {
  if (rank == null && !top && score === undefined) return null;
  return (
    <div className="cc-badges">
      <span className="cc-badges-left">
        {rank != null && <span className="cc-rank num" aria-label={`Rank ${rank}`}>#{rank}</span>}
        {top && <span className="tag action cc-top">Top pick</span>}
      </span>
      {score !== undefined && (
        score == null ? (
          <span className="cc-score faint">not scored yet</span>
        ) : (
          <span className="cc-score num" title={scoreTitle}>
            <span className="sr-only">{scoreLabel}: </span><b>{score}</b><span className="cc-of">/100</span>
          </span>
        )
      )}
    </div>
  );
}

/** The picture as the thing to tap: a button that opens the player, a link to the post, or (nothing to play) only the picture. */
function CardMedia({ playable, title, onWatch, children }: { playable: Playable; title: string; onWatch(): void; children: ReactNode }) {
  if (playable.kind === 'file') {
    return (
      <button type="button" className="cc-pic" aria-label={`Watch: ${title}`} onClick={onWatch}>
        {children}
        <span className="cc-play" aria-hidden="true">
          <Play />
        </span>
      </button>
    );
  }
  if (playable.kind === 'link') {
    const where = playable.label.replace(/\s*↗$/, '');
    return (
      <a className="cc-pic" href={playable.url} target="_blank" rel="noopener noreferrer" aria-label={`${where}: ${title} (a new tab)`}>
        {children}
        <span className="cc-play cc-play-link" aria-hidden="true">
          <Play /> {playable.label}
        </span>
      </a>
    );
  }
  return <div className="cc-pic">{children}</div>;
}

/** The card's picture: each of its files in turn (signed for the owner's browser; one that fails gives way to the next), then the
 * pick's own thumbnail, then its platform tile. */
export function CardPicture({ picture, title }: { picture: CardPictureSpec; title: string }) {
  const { backend } = useStudio();
  const key = picture.sources.map((s) => s.path).join('|');
  const [pos, setPos] = useState<PicturePos>({ step: 0, resigned: false });
  const [src, setSrc] = useState<string | null>(null);
  const [thumbFailed, setThumbFailed] = useState(false);
  const current = picture.sources[pos.step] ?? null;

  useEffect(() => {
    setPos({ step: 0, resigned: false });
    setThumbFailed(false);
  }, [key, picture.thumb.thumbnail_url]);

  // each file is signed for the owner's browser; a file that fails to load is signed once more (the URL may have expired), and
  // only then gives way to the next one (afterPictureError)
  useEffect(() => {
    let live = true;
    setSrc(null);
    if (current) {
      void backend.previewUrl(current.path).then((u) => {
        if (!live) return;
        if (u) setSrc(u);
        else setPos((p) => ({ step: p.step + 1, resigned: false }));
      });
    }
    return () => {
      live = false;
    };
  }, [backend, current?.path, pos.step, pos.resigned]);

  if (current) {
    if (!src) return <span className="cc-img cc-loading" aria-hidden="true" />;
    return (
      <img
        className={`cc-img ${current.kind}`} src={src} alt={`A frame of ${title}`} loading="lazy" decoding="async"
        onError={() => setPos(afterPictureError)}
      />
    );
  }
  const spec = thumbFor(picture.thumb, { imageFailed: thumbFailed });
  if (spec.kind === 'image') {
    return (
      <img
        className={`cc-img${spec.aspect === '16:9' ? ' wide' : ''}`} src={spec.src!} alt={spec.alt} loading="lazy" decoding="async"
        referrerPolicy="no-referrer" onError={() => setThumbFailed(true)}
      />
    );
  }
  return (
    <span className={`cc-img thumb-tile plat-${spec.platform}`} role="img" aria-label={spec.alt}>
      <b className="mono">{spec.code}</b>
      {spec.handle && <span className="who">{spec.handle}</span>}
    </span>
  );
}

/** "Open original ↗" (a card's small controls): the post a pasted or filed link came from, in a new tab; nothing without one. */
export function OriginalLink({ url, label = 'Open original' }: { url: string | null | undefined; label?: string }) {
  const link = originalLink(url);
  if (!link) return null;
  return (
    <a className="cc-textlink" href={link.url} target="_blank" rel="noopener noreferrer">
      {label} <ExternalLink size={13} aria-hidden="true" />
    </a>
  );
}

/** The ready card's action: the same tick the Make bar adds up ("＋ Add" / "✓ In your list"; "Make this" until 2026-10-15); nothing is spent
 * before its confirm. A plain button whose accessible name is its visible text ("Add" / "In your list"; the mark is `aria-hidden`), so
 * what a screen reader says is what the eye reads (Task 11 ruling: no stable `aria-label`, no `aria-pressed`). */
export function MakeToggle({ ticked, disabled, onToggle, describedBy }: {
  ticked: boolean;
  disabled?: boolean;
  onToggle(on: boolean): void;
  describedBy?: string;
}) {
  const t = ticked ? MAKE_TOGGLE.on : MAKE_TOGGLE.off;
  return (
    <button
      type="button" className={`btn block cc-toggle ${ticked ? 'primary' : 'line'}`}
      disabled={disabled} aria-describedby={describedBy} onClick={() => onToggle(!ticked)}
    >
      <span className="cc-mark" aria-hidden="true">{t.mark}</span> {t.text}
    </button>
  );
}

/** Remove a clip, in two steps (Task 11 fix 1): the first tap turns the button into "Remove this clip? Yes, remove / Keep it" (44 px
 * buttons, the focus on Keep it: a mis-tap on a phone must not delete a clip); only "Yes, remove" removes (lib/clipcard removeStep). */
export function RemoveClip({ title, disabled, onRemove }: { title: string; disabled?: boolean; onRemove(): void }) {
  const [step, setStep] = useState<RemoveStep>('idle');
  const opener = useRef<HTMLButtonElement>(null);
  const act = (action: 'ask' | 'confirm' | 'cancel') => {
    const next = removeStep(step, action);
    setStep(next.step);
    if (next.remove) onRemove();
    else if (action === 'cancel') window.setTimeout(() => opener.current?.focus(), 0); // back to the button that asked
  };
  if (step === 'asking') {
    return (
      <div className="remove-ask" role="group" aria-label={`Remove ${title}?`}>
        <span className="small">Remove this clip?</span>
        <span className="remove-buttons">
          <button type="button" className="btn danger" disabled={disabled} onClick={() => act('confirm')}>
            Yes, remove
          </button>
          {/* the focus lands on Keep it: Enter on a mis-tap must not remove the clip */}
          <button type="button" className="btn line" autoFocus disabled={disabled} onClick={() => act('cancel')}>
            Keep it
          </button>
        </span>
      </div>
    );
  }
  return (
    <button ref={opener} type="button" className="cc-textlink" disabled={disabled} onClick={() => act('ask')} aria-label={`Remove ${title}`}>
      Remove
    </button>
  );
}

/**
 * The player (a Sheet: focus kept inside, Escape and Close shut it, the page behind inert): full screen on a phone, a centred box
 * on a wider screen. The section plays with its sound (the tap allowed it; if the browser still holds it back, its play button
 * is there) and goes back to its start at its end. Under it the title, the score and reason, the price, the character and the
 * card's own action (the same state: a change here is a change on the card), then Open the original and Close.
 */
export function ClipPlayerSheet({
  id, title, playable, picture, score, scoreLabel = 'Score', checkScore = false, reason, price, character, action, original, onClose,
}: {
  id: string;
  title: string;
  playable: Extract<Playable, { kind: 'file' }>;
  picture: CardPictureSpec;
  score?: number | null;
  scoreLabel?: string;
  /** The score is the free check's: the score test's label stands beside it (see ClipCardProps.checkScore). */
  checkScore?: boolean;
  reason?: ReactNode;
  price?: ReactNode;
  character?: string | null;
  action?: (place: ActionPlace) => ReactNode;
  original: string | null;
  onClose(): void;
}) {
  const { backend } = useStudio();
  const caution = useScoreNote();
  const [url, setUrl] = useState<string | null>(null);
  const [state, setState] = useState<'loading' | 'ready' | 'none' | 'broken'>('loading');
  const video = useRef<HTMLVideoElement>(null);
  const uid = useId();
  const titleId = `${id}-sheet-title`;
  const priceId = `${id}-sheet-price`;
  const { start, end } = playable;
  const link = originalLink(original); // the sheet checks it too: only an https post on TikTok, Instagram or YouTube is a link

  useEffect(() => {
    let live = true;
    setState('loading');
    void backend.previewUrl(playable.path).then((u) => {
      if (!live) return;
      setUrl(u);
      setState(u ? 'ready' : 'none');
    });
    return () => {
      live = false;
    };
  }, [backend, playable.path]);

  const back = (v: HTMLVideoElement) => {
    v.currentTime = start;
    void v.play().catch(() => undefined);
  };
  const onTime = (e: SyntheticEvent<HTMLVideoElement>) => {
    const v = e.currentTarget;
    if (shouldLoopBack(v.currentTime, start, end)) back(v);
  };
  // a browser pauses at a fragment's end on its own: that pause is the loop's, not the owner's
  const onPause = (e: SyntheticEvent<HTMLVideoElement>) => {
    const v = e.currentTarget;
    if (end != null && shouldLoopBack(v.currentTime, start, end)) back(v);
  };

  return (
    <Sheet title={<>Watch<span className="sr-only">: {title}</span></>} onClose={onClose} className="player-sheet" initialFocus="[data-sheet-close]">
      <div className={playable.note ? 'player-body noted' : 'player-body'}>
        <div className="player-frame">
          {state === 'ready' && url ? (
            <video
              ref={video} src={withFragment(url, start, end)} controls playsInline autoPlay preload="auto" loop={end == null}
              aria-label={`${title}: the section we would use`} onTimeUpdate={onTime} onPause={onPause}
              onEnded={(e) => back(e.currentTarget)} onError={() => setState('broken')}
              // iOS ignores autoplay until the data is in: play when it is (a refusal is fine, the controls are the fallback)
              onLoadedData={(e) => void e.currentTarget.play().catch(() => undefined)}
            />
          ) : (
            <div className="player-none">
              <CardPicture picture={picture} title={title} />
              <p className="small player-note" role="status" id={`${uid}-note`}>
                {state === 'loading' ? 'Loading the clip…' : state === 'broken' ? 'The clip could not be played here. Try again later.' : 'No preview to play yet.'}
              </p>
            </div>
          )}
        </div>
        {playable.note && <p className="small muted player-section-note">{playable.note}</p>}
        <div className="player-facts">
          <span className="cc-title player-title" id={titleId}>{title}</span>
          {(score != null || reason) && (
            <span className="small">
              {score != null && (
                <span className="num player-score">
                  <span className="sr-only">{scoreLabel}: </span><b>{score}</b><span className="muted">/100</span>
                  {showsScoreCaution(score, checkScore) && <ScoreCaution note={caution} className="player-score-note" />}
                </span>
              )}
              {score != null && reason ? <span className="muted"> · </span> : null}
              {reason && <span className="muted">{reason}</span>}
            </span>
          )}
          {price && <span className="small num" id={priceId}>{price}</span>}
          {character && <span className="small">{character}</span>}
        </div>
        {action && <div className="player-action">{action({ where: 'sheet', describedBy: price ? `${titleId} ${priceId}` : titleId })}</div>}
        <div className="sheet-actions">
          {link && (
            <a className="btn ghost" href={link.url} target="_blank" rel="noopener noreferrer">
              Open the original <ExternalLink aria-hidden="true" />
            </a>
          )}
          <button type="button" className="btn line" data-sheet-close onClick={onClose}>
            Close
          </button>
        </div>
      </div>
    </Sheet>
  );
}

