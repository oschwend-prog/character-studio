// The saved clips ranked per character (terminal v3, spec 5.2 and 6). A section per live character: "Needs you" first (clips the
// studio filed under him that wait for a character choice), then his Ready clips ranked 1, 2, 3... by score with the score, the
// one-line reason, the price and a Top pick badge on the first three scored ones (an unscored clip is "not scored yet"), then
// what is on its way and done, the blocked and failed folded into one closed row. Each Ready clip has a tick box (the MakeBar
// below adds them up and asks before anything is spent) and "Use for another character" (a version for a like-for-like
// character, free: studio.copy_drop). `compact` is Today's "Make these": his top 3 Ready clips only.
import { ArrowRight, CircleAlert } from 'lucide-react';
import { useState } from 'react';
import { CHIP_CLASS, CHIP_LABEL, characterConfirm, clipChip } from '../lib/clipstatus';
import { cantUseLine, clipsByCharacter, isTopPick, readyWithChoice, sectionSummary, versionsLine } from '../lib/clipsview';
import { characterChoice, characterMenu, dropCredits, dropLine, dropTitle, sectionLabel, effectiveDrop } from '../lib/drop';
import { href } from '../lib/hooks';
import { reuseTargets, scoreOf, topPicks } from '../lib/ranking';
import { activeRoster, nameOf, type RosterEntry } from '../lib/roster';
import { useStudio } from '../lib/store';
import type { TrackerRow } from '../lib/types';
import { CharacterCell, DropThumb } from './DropsTable';
import { Avatar, Spinner } from './ui';

const message = (e: unknown) => (e instanceof Error ? e.message : String(e));

export function RankedClips({
  rows, characters, ticked, onTick, now, compact = false,
}: {
  /** The dropped clips to show (rows with a drop card; the Clips page's list). */
  rows: ReadonlyArray<TrackerRow>;
  /** The live characters, in the owner's order: one section each. */
  characters: ReadonlyArray<{ slug: string; name: string }>;
  ticked: ReadonlySet<string>;
  onTick(id: string, on: boolean): void;
  now: number;
  compact?: boolean;
}) {
  const { data } = useStudio();
  const { groups, others } = clipsByCharacter(rows, characters);
  const names = new Map((data?.characters ?? []).map((c) => [c.slug, c.name]));

  if (!characters.length) {
    return (
      <div className="panel empty">
        <b>No live character yet.</b>
        <span className="muted small">A character's clips are ranked here once his status is live.</span>
      </div>
    );
  }

  if (compact) {
    const anyReady = groups.some((g) => g.ready.length > 0);
    return (
      <div className="stack ranked compact" style={{ gap: 14 }}>
        {!anyReady && (
          <p className="small muted" style={{ margin: 0 }}>
            Nothing is ready to make. Save videos to the clips folder or add them in <a href={href('clips')}>Clips</a>: each is checked for
            free, and the best ones are ranked here.
          </p>
        )}
        {groups.map((g) => {
          const top = topPicks(g.ready, 3);
          return (
            <section key={g.slug} className={`pick-sec ${g.slug}`} aria-labelledby={`make-${g.slug}`}>
              <header className="pick-sec-head">
                <Avatar slug={g.slug} name={g.name} size={32} />
                <h3 className="h2" id={`make-${g.slug}`}>{g.name}</h3>
                <span className="small muted num sec-count">{readyWithChoice(g.ready.length, g.needsYou.length)}</span>
              </header>
              {top.length ? (
                <ol className="rank-list" aria-label={`${g.name}’s best ready clips`}>
                  {top.map((r, i) => (
                    <ReadyItem key={r.pick_id} row={r} rank={i + 1} top={isTopPick(r, i)} ticked={ticked.has(r.pick_id)} onTick={onTick} compact
                      versions={versionsLine(r, data?.tracker ?? rows, names)} />
                  ))}
                </ol>
              ) : (
                <p className="small muted pick-sec-empty">
                  Nothing ready to make for {g.name}.
                  {g.needsYou.length ? ` ${g.needsYou.length === 1 ? '1 clip waits' : `${g.needsYou.length} clips wait`} for your choice of character.` : ''}
                </p>
              )}
              <a className="link" href={href('clips', undefined, { c: g.slug })}>
                See all of {g.name}’s clips{g.ready.length > top.length ? ` (${g.ready.length} ready)` : ''} <ArrowRight size={14} aria-hidden="true" />
              </a>
            </section>
          );
        })}
      </div>
    );
  }

  return (
    <div className="stack ranked">
      {groups.map((g) => (
        <CharacterSection key={g.slug} group={g} rows={data?.tracker ?? rows} names={names} ticked={ticked} onTick={onTick} now={now} />
      ))}
      {others.length > 0 && (
        <p className="small muted" style={{ margin: 0 }}>
          {others.length === 1 ? '1 clip has' : `${others.length} clips have`} no live character (none chosen yet, or a paused one):{' '}
          <a href={href('clips', undefined, { v: 'all' })}>see All clips</a>.
        </p>
      )}
    </div>
  );
}

function CharacterSection({
  group: g, rows, names, ticked, onTick, now,
}: {
  group: ReturnType<typeof clipsByCharacter>['groups'][number];
  rows: ReadonlyArray<TrackerRow>;
  names: ReadonlyMap<string, string>;
  ticked: ReadonlySet<string>;
  onTick(id: string, on: boolean): void;
  now: number;
}) {
  const { data } = useStudio();
  const roster = activeRoster(data?.characters);
  const empty = !g.needsYou.length && !g.ready.length && !g.onTheWay.length && !g.done.length && !g.problems.length;
  const DONE_SHOWN = 5;
  return (
    <section className={`pick-sec ${g.slug}`} id={`clips-${g.slug}`} aria-labelledby={`clips-${g.slug}-name`}>
      <header className="pick-sec-head">
        <Avatar slug={g.slug} name={g.name} size={40} />
        <h2 className="h2" id={`clips-${g.slug}-name`}>
          <a className="name-link" href={href('artist', g.slug)}>{g.name}</a>
        </h2>
        <span className="small muted num sec-count">{sectionSummary(g)}</span>
      </header>

      {empty && (
        <p className="small muted pick-sec-empty">
          No clips for {g.name} yet. Save a video to the clips folder or add one above: each is checked for free.
        </p>
      )}

      {g.needsYou.length > 0 && (
        <div className="pick-group">
          <h3 className="pick-group-head">Needs you <span className="count">{g.needsYou.length}</span></h3>
          <p className="hint" style={{ margin: 0 }}>The studio filed these under {g.name}. Keep him (free) or choose another character.</p>
          <ul className="rank-list">
            {g.needsYou.map((r) => <NeedsYouItem key={r.pick_id} row={r} roster={roster} />)}
          </ul>
        </div>
      )}

      {g.ready.length > 0 ? (
        <div className="pick-group">
          <h3 className="pick-group-head">Ready to make, best first <span className="count">{g.ready.length}</span></h3>
          <ol className="rank-list">
            {g.ready.map((r, i) => (
              <ReadyItem key={r.pick_id} row={r} rank={i + 1} top={isTopPick(r, i)} ticked={ticked.has(r.pick_id)} onTick={onTick}
                versions={versionsLine(r, rows, names)} />
            ))}
          </ol>
        </div>
      ) : (
        !empty && <p className="small muted pick-sec-empty">Nothing ready to make for {g.name}.</p>
      )}

      {g.onTheWay.length > 0 && (
        <div className="pick-group">
          <h3 className="pick-group-head">On the way <span className="count">{g.onTheWay.length}</span></h3>
          <ul className="rank-list">
            {g.onTheWay.map((r) => <QuietItem key={r.pick_id} row={r} now={now} versions={versionsLine(r, rows, names)} />)}
          </ul>
        </div>
      )}

      {g.done.length > 0 && (
        <div className="pick-group">
          <h3 className="pick-group-head">Done <span className="count">{g.done.length}</span></h3>
          <ul className="rank-list">
            {g.done.slice(0, DONE_SHOWN).map((r) => <QuietItem key={r.pick_id} row={r} now={now} versions={versionsLine(r, rows, names)} />)}
          </ul>
          {g.done.length > DONE_SHOWN && (
            <a className="link" href={href('clips', undefined, { v: 'all', f: 'done' })}>
              {g.done.length - DONE_SHOWN} more in All clips <ArrowRight size={14} aria-hidden="true" />
            </a>
          )}
        </div>
      )}

      {g.problems.length > 0 && (
        <details className="cant-use">
          <summary>
            <CircleAlert size={15} aria-hidden="true" /> {cantUseLine(g.problems.length)}
          </summary>
          <ul className="cant-use-list">
            {g.problems.map((r) => (
              <li key={r.pick_id}>
                <b>{dropTitle(r)}</b>
                <span className="error-text">{dropLine(r.drop_card!, now, Boolean(r.owner_clip_path))}</span>
              </li>
            ))}
          </ul>
          <a className="link" href={href('clips', undefined, { v: 'all', f: 'problems' })}>
            Try again or remove them in All clips <ArrowRight size={14} aria-hidden="true" />
          </a>
        </details>
      )}
    </section>
  );
}

/** A Ready clip: tick box, rank, Top pick, score and reason, price; the versions line and the reuse menu (not in compact). */
function ReadyItem({
  row, rank, top, ticked, onTick, versions, compact = false,
}: {
  row: TrackerRow;
  rank: number;
  top: boolean;
  ticked: boolean;
  onTick(id: string, on: boolean): void;
  versions: string | null;
  compact?: boolean;
}) {
  const d = row.drop_card!;
  const title = dropTitle(row);
  const score = scoreOf(row);
  const reason = score != null && typeof d.score?.reason === 'string' && d.score.reason.trim() ? d.score.reason.trim() : null;
  const priced = d.credits != null;
  const credits = priced ? dropCredits(d, d.adjust ?? {}) : null;
  const e = effectiveDrop(d, d.adjust ?? {});
  const tickId = `tick-${compact ? 'c' : 'f'}-${row.pick_id}`;
  return (
    <li className="rank-item" data-char={row.character_slug ?? 'none'} data-ticked={ticked}>
      <label className="tick" htmlFor={tickId}>
        <input
          id={tickId} type="checkbox" checked={ticked} disabled={!priced} onChange={(ev) => onTick(row.pick_id, ev.target.checked)}
          aria-label={`Tick to make: ${title}${credits != null ? `, about ${credits} credits` : ''}`}
        />
      </label>
      <DropThumb row={row} />
      <div className="rank-main">
        <div className="rank-top">
          <span className="rank-no num" aria-label={`Rank ${rank}`}>#{rank}</span>
          {top && <span className="tag action">Top pick</span>}
          {score != null ? (
            <span className="rank-score num" title="The free check's score: how likely the clip gets views with him in it">
              <b>{score}</b><span className="muted">/100</span>
            </span>
          ) : (
            <span className="faint small">not scored yet</span>
          )}
        </div>
        <span className="rank-title">{title}</span>
        {reason && <span className="small muted rank-reason">{reason}</span>}
        <span className="small num">
          {credits != null ? <b>about {credits} credits</b> : <span className="faint">priced by the check</span>}
          {d.window && <span className="muted"> · {sectionLabel(e.start_s, e.length_s)}</span>}
        </span>
        {versions && <span className="small muted">{versions}</span>}
        {!compact && <ReuseMenu row={row} title={title} />}
      </div>
    </li>
  );
}

/** "Use for another character" (spec 4): a version for a like-for-like character, checked again in his voice for free. Picking a
 * name asks once more on the card ("Use this clip for Lenny Gold too? Yes · Cancel": a family has only 3 places, a mis-tap on a
 * phone must not take one). A refusal of copy_drop is shown on the card in its own plain line; the data is reloaded either way. */
function ReuseMenu({ row, title }: { row: TrackerRow; title: string }) {
  const { data, backend, run, toast, busy } = useStudio();
  const [refusal, setRefusal] = useState<string | null>(null);
  const [pending, setPending] = useState<{ slug: string; name: string } | null>(null);
  const targets = reuseTargets(row, data?.characters ?? [], data?.tracker ?? []);
  const key = `copy-${row.pick_id}`;
  const working = busy.has(key);
  if (!targets.length && !refusal && !pending) return null;
  const id = `reuse-${row.pick_id}`;

  const copy = async ({ slug, name }: { slug: string; name: string }) => {
    setRefusal(null);
    let refused: string | null = null;
    await run(key, async () => {
      try {
        await backend.copyDrop(row.pick_id, slug);
      } catch (e) {
        refused = message(e); // shown on the card, not as a toast; run still reloads the data
      }
    });
    setPending(null);
    if (refused) setRefusal(refused);
    else toast(`${name} gets this clip too: checking it in his voice (free)`);
  };

  return (
    <div className="reuse">
      {pending ? (
        <div className="reuse-confirm" role="group" aria-label={`Use this clip for ${pending.name}?`}>
          <span className="small">Use this clip for {pending.name} too? It is checked again for him, free.</span>
          <span className="reuse-buttons">
            <button type="button" className="btn line" autoFocus disabled={working} aria-busy={working} onClick={() => void copy(pending)}>
              {working && <Spinner />} Yes
            </button>
            <button type="button" className="btn ghost" disabled={working} onClick={() => setPending(null)}>
              Cancel
            </button>
          </span>
        </div>
      ) : (
        targets.length > 0 && (
          <>
            <label className="sr-only" htmlFor={id}>Use {title} for another character</label>
            <select
              id={id} className="select reuse-select" value="" disabled={working}
              onChange={(e) => {
                const t = targets.find((x) => x.slug === e.target.value);
                if (t) {
                  setRefusal(null);
                  setPending({ slug: t.slug, name: t.name ?? nameOf(t.slug) });
                }
              }}
            >
              <option value="">Use for another character…</option>
              {targets.map((t) => (
                <option key={t.slug} value={t.slug}>{t.name} (free check)</option>
              ))}
            </select>
          </>
        )
      )}
      {refusal && (
        <p className="error-text" role="alert" style={{ margin: 0 }}>
          {refusal}
        </p>
      )}
    </div>
  );
}

/** A clip the studio filed under him: keep him with one tap (free) or choose another in the menu (checked again, free). */
function NeedsYouItem({ row, roster }: { row: TrackerRow; roster: ReadonlyArray<RosterEntry> }) {
  const { backend, run, busy } = useStudio();
  const d = row.drop_card!;
  const menu = characterMenu(row, roster);
  const charKey = `char-${row.pick_id}`;
  const working = busy.has(charKey) || busy.has(`drop-${row.pick_id}`);
  const credits = d.credits != null ? dropCredits(d, d.adjust ?? {}) : null;
  const choose = (slug: string) => {
    if (characterChoice(menu, row.character_slug, slug) === 'none') return;
    const name = roster.find((c) => c.slug === slug)?.name ?? slug;
    void run(
      charKey, () => backend.setDropCharacter(row.pick_id, slug),
      slug === row.character_slug ? `${name} it is` : `${name}: checking it again in his voice (free)`,
    );
  };
  return (
    <li className="rank-item no-tick" data-char={row.character_slug ?? 'none'}>
      <DropThumb row={row} />
      <div className="rank-main">
        <span className="rank-title">{dropTitle(row)}</span>
        {credits != null && <span className="small num muted">about {credits} credits once you choose</span>}
        <div className="needs-choice">
          <CharacterCell row={row} menu={menu} confirm={characterConfirm(row, roster)} working={working} onChoose={choose} />
        </div>
      </div>
    </li>
  );
}

/** A clip on its way or done: its chip, one line, and Review in Videos when it waits for his OK. */
function QuietItem({ row, now, versions }: { row: TrackerRow; now: number; versions: string | null }) {
  const d = row.drop_card!;
  const chip = clipChip(row);
  const line = chip === 'checking' || chip === 'adding' ? dropLine(d, now, Boolean(row.owner_clip_path)) : null;
  return (
    <li className="rank-item no-tick quiet" data-char={row.character_slug ?? 'none'}>
      <DropThumb row={row} />
      <div className="rank-main">
        <span className="rank-title">{dropTitle(row)}</span>
        <span className="small">
          <span className={`drop-state ${CHIP_CLASS[chip]}`}>{CHIP_LABEL[chip]}</span>
          {line && <span className="muted"> {line}</span>}
        </span>
        {versions && <span className="small muted">{versions}</span>}
        {row.clip_state === 'awaiting_approval' && row.clip_id && (
          <a className="btn line rank-review" href={href('videos', row.clip_id)}>Review in Videos</a>
        )}
      </div>
    </li>
  );
}
