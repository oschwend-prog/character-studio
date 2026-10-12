// The saved clips ranked per character (terminal v3, spec 5.2 and 6). A section per live character: "Needs you" first (clips the
// studio filed under him that wait for a character choice), then his Ready clips ranked 1, 2, 3... by score with the score, the
// one-line reason, the price and a Top pick badge on the first three scored ones (an unscored clip is "not scored yet"), then
// what is on its way and done, the blocked and failed folded into one closed row. Every clip is a big card you can tap to watch
// (ClipCard, Task 11, owner 2026-10-08). Each Ready card has the Make toggle ("＋ Make this" / "✓ In your list": the same tick the
// MakeBar below adds up, and it asks before anything is spent) and, under More, "Use for another character" (a version for a
// like-for-like character, free: studio.copy_drop). Under his Ready clips, "Worth saving": his top 5 new hits of the daily cloud
// pull (spec 10, Hits.tsx). A clip not made yet has the Keep toggle under More (retention never deletes a kept clip). `compact` is
// Today's "Make these": his top 3 Ready clips and, when he has one, an Explore clip (one suggestion in four, learning test A).
import { ArrowRight, CircleAlert } from 'lucide-react';
import { useState } from 'react';
import { cardPrice, originalLink, playableFor } from '../lib/clipcard';
import { CHIP_CLASS, CHIP_LABEL, characterConfirm, clipChip } from '../lib/clipstatus';
import { cantUseLine, clipsByCharacter, isTopPick, readyWithChoice, sectionSummary, versionsLine } from '../lib/clipsview';
import { characterChoice, characterMenu, dropCredits, dropLine, dropTitle, sectionLabel, effectiveDrop } from '../lib/drop';
import { keepable } from '../lib/hits';
import { href } from '../lib/hooks';
import { reuseTargets, scoreOf, suggestedClips } from '../lib/ranking';
import { activeRoster, nameOf, type RosterEntry } from '../lib/roster';
import { useStudio } from '../lib/store';
import type { TrackerRow } from '../lib/types';
import { ClipCard, ClipGrid, MakeToggle, OriginalLink, dropPicture } from './ClipCard';
import { CharacterCell } from './DropsTable';
import { WorthSaving } from './Hits';
import { KeepToggle } from './KeepToggle';
import { Avatar, Spinner } from './ui';

const message = (e: unknown) => (e instanceof Error ? e.message : String(e));

const SCORE_TITLE = 'The free check’s score: how likely the clip gets views with him in it';

/** The check's one line why the clip may get views, shown only with its score. */
const scoreReason = (row: TrackerRow): string | null => {
  const r = row.drop_card?.score?.reason;
  return scoreOf(row) != null && typeof r === 'string' && r.trim() ? r.trim() : null;
};

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
  const { groups, others, deciding } = clipsByCharacter(rows, characters);
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
          const top = suggestedClips(g.ready, 3);
          return (
            <section key={g.slug} className={`pick-sec ${g.slug}`} aria-labelledby={`make-${g.slug}`}>
              <header className="pick-sec-head">
                <Avatar slug={g.slug} name={g.name} size={32} />
                <h3 className="h2" id={`make-${g.slug}`}>{g.name}</h3>
                <span className="small muted num sec-count">{readyWithChoice(g.ready.length, g.needsYou.length)}</span>
              </header>
              {top.length ? (
                <ClipGrid label={`${g.name}’s best ready clips, best first`}>
                  {top.map(({ row: r, explore }, i) => (
                    <ReadyCard key={r.pick_id} row={r} rank={i + 1} top={!explore && isTopPick(r, i)} explore={explore}
                      ticked={ticked.has(r.pick_id)} onTick={onTick} compact versions={versionsLine(r, data?.tracker ?? rows, names)} />
                  ))}
                </ClipGrid>
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
      {deciding.length > 0 && (
        <section className="pick-sec" id="clips-recommend" aria-labelledby="clips-recommend-name">
          <header className="pick-sec-head">
            <h2 className="h2" id="clips-recommend-name"><span aria-hidden="true">★ </span>Recommend</h2>
            <span className="small muted num sec-count">{deciding.length === 1 ? '1 clip' : `${deciding.length} clips`}</span>
          </header>
          <p className="small muted" style={{ margin: 0 }}>
            Chosen after the check: once the studio has looked at the clip, it goes to the character who fits.
          </p>
          <ClipGrid label="Clips waiting for the check to choose a character">
            {deciding.map((r) => <QuietCard key={r.pick_id} row={r} now={now} versions={null} />)}
          </ClipGrid>
        </section>
      )}
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
          No clips for {g.name} yet. Save a video to the clips folder, add one above or use one of his hits below: each is checked for
          free.
        </p>
      )}

      {g.needsYou.length > 0 && (
        <div className="pick-group">
          <h3 className="pick-group-head">Needs you <span className="count">{g.needsYou.length}</span></h3>
          <p className="hint" style={{ margin: 0 }}>The studio filed these under {g.name}. Keep him (free) or choose another character.</p>
          <ClipGrid label={`Needs your choice of character, ${g.needsYou.length}`}>
            {g.needsYou.map((r) => <NeedsYouCard key={r.pick_id} row={r} roster={roster} />)}
          </ClipGrid>
        </div>
      )}

      {g.ready.length > 0 ? (
        <div className="pick-group">
          <h3 className="pick-group-head">Ready to make, best first <span className="count">{g.ready.length}</span></h3>
          <ClipGrid label={`${g.name}’s clips ready to make, best first`}>
            {g.ready.map((r, i) => (
              <ReadyCard key={r.pick_id} row={r} rank={i + 1} top={isTopPick(r, i)} ticked={ticked.has(r.pick_id)} onTick={onTick}
                versions={versionsLine(r, rows, names)} />
            ))}
          </ClipGrid>
        </div>
      ) : (
        !empty && <p className="small muted pick-sec-empty">Nothing ready to make for {g.name}.</p>
      )}

      <WorthSaving slug={g.slug} name={g.name} readyCount={g.ready.length} now={now} />

      {g.onTheWay.length > 0 && (
        <div className="pick-group">
          <h3 className="pick-group-head">On the way <span className="count">{g.onTheWay.length}</span></h3>
          <ClipGrid label={`${g.name}’s clips on the way`}>
            {g.onTheWay.map((r) => <QuietCard key={r.pick_id} row={r} now={now} versions={versionsLine(r, rows, names)} />)}
          </ClipGrid>
        </div>
      )}

      {g.done.length > 0 && (
        <div className="pick-group">
          <h3 className="pick-group-head">Done <span className="count">{g.done.length}</span></h3>
          <ClipGrid label={`${g.name}’s clips done`}>
            {g.done.slice(0, DONE_SHOWN).map((r) => <QuietCard key={r.pick_id} row={r} now={now} versions={versionsLine(r, rows, names)} />)}
          </ClipGrid>
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

/** A Ready clip: its card with the rank, Top pick, score and reason, price and section, and the Make toggle (the tick the Make bar
 * adds up); the versions line; under More, "Use for another character", Keep and the original post (not in compact). */
function ReadyCard({
  row, rank, top, explore = false, ticked, onTick, versions, compact = false,
}: {
  row: TrackerRow;
  rank: number;
  top: boolean;
  explore?: boolean;
  ticked: boolean;
  onTick(id: string, on: boolean): void;
  versions: string | null;
  compact?: boolean;
}) {
  const { data } = useStudio();
  const d = row.drop_card!;
  const title = dropTitle(row);
  const priced = d.credits != null;
  const credits = priced ? dropCredits(d, d.adjust ?? {}) : null;
  const e = effectiveDrop(d, d.adjust ?? {});
  const original = originalLink(row.url)?.url ?? null;
  const more = !compact && (keepable(row) || original != null || reuseTargets(row, data?.characters ?? [], data?.tracker ?? []).length > 0);
  return (
    <ClipCard
      id={`${compact ? 'c' : 'f'}-${row.pick_id}`} title={title} picture={dropPicture(row, title)} playable={playableFor(row)}
      rank={rank} top={top} explore={explore} score={scoreOf(row)} scoreTitle={SCORE_TITLE} reason={scoreReason(row)}
      price={cardPrice(credits, d.window ? e.length_s : null)}
      sheetPrice={credits != null ? `about ${credits} credits${d.window ? ` · ${sectionLabel(e.start_s, e.length_s)}` : ''}` : 'priced by the check'}
      extra={versions && <span className="small muted">{versions}</span>}
      ticked={ticked} dataChar={row.character_slug ?? 'none'} original={original}
      action={({ describedBy }) => (
        <MakeToggle ticked={ticked} disabled={!priced} onToggle={(on) => onTick(row.pick_id, on)} describedBy={describedBy} />
      )}
      more={more ? (
        <>
          <ReuseMenu row={row} title={title} />
          <KeepToggle row={row} />
          <OriginalLink url={row.url} />
        </>
      ) : undefined}
    />
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
            <button type="button" className="btn line" disabled={working} aria-busy={working} onClick={() => void copy(pending)}>
              {working && <Spinner />} Yes
            </button>
            {/* the focus lands on Cancel: Enter on a mis-picked name must not take one of the family's 3 places */}
            <button type="button" className="btn ghost" autoFocus disabled={working} onClick={() => setPending(null)}>
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
function NeedsYouCard({ row, roster }: { row: TrackerRow; roster: ReadonlyArray<RosterEntry> }) {
  const { backend, run, busy } = useStudio();
  const d = row.drop_card!;
  const title = dropTitle(row);
  const menu = characterMenu(row, roster);
  const charKey = `char-${row.pick_id}`;
  const working = busy.has(charKey) || busy.has(`drop-${row.pick_id}`);
  const credits = d.credits != null ? dropCredits(d, d.adjust ?? {}) : null;
  const score = scoreOf(row);
  const original = originalLink(row.url)?.url ?? null;
  const choose = (slug: string) => {
    if (characterChoice(menu, row.character_slug, slug) === 'none') return;
    const name = roster.find((c) => c.slug === slug)?.name ?? slug;
    void run(
      charKey, () => backend.setDropCharacter(row.pick_id, slug),
      slug === row.character_slug ? `${name} it is` : `${name}: checking it again in his voice (free)`,
    );
  };
  return (
    <ClipCard
      id={`n-${row.pick_id}`} title={title} picture={dropPicture(row, title)} playable={playableFor(row)}
      score={score ?? undefined} scoreTitle={SCORE_TITLE} reason={scoreReason(row)}
      price={credits != null ? `about ${credits} credits once you choose` : undefined}
      dataChar={row.character_slug ?? 'none'} original={original}
      action={({ where }) => (
        <div className="needs-choice">
          <CharacterCell
            row={row} menu={menu} confirm={characterConfirm(row, roster)} working={working} onChoose={choose}
            idPrefix={where === 'sheet' ? 'pl-char' : 'dt-char'}
          />
        </div>
      )}
      more={keepable(row) || original ? (
        <>
          <KeepToggle row={row} />
          <OriginalLink url={row.url} />
        </>
      ) : undefined}
    />
  );
}

/** A clip on its way or done: its chip, one line, and Review in Videos when it waits for his OK. */
function QuietCard({ row, now, versions }: { row: TrackerRow; now: number; versions: string | null }) {
  const d = row.drop_card!;
  const title = dropTitle(row);
  const chip = clipChip(row);
  const line = chip === 'checking' || chip === 'adding' ? dropLine(d, now, Boolean(row.owner_clip_path)) : null;
  const original = originalLink(row.url)?.url ?? null;
  return (
    <ClipCard
      id={`q-${row.pick_id}`} title={title} picture={dropPicture(row, title)} playable={playableFor(row)} className="quiet"
      extra={versions && <span className="small muted">{versions}</span>} dataChar={row.character_slug ?? 'none'} original={original}
      action={() => (
        <>
          <span className="small cc-status">
            <span className={`drop-state ${CHIP_CLASS[chip]}`}>{CHIP_LABEL[chip]}</span>
            {line && <span className="muted"> {line}</span>}
          </span>
          {row.clip_state === 'awaiting_approval' && row.clip_id && (
            <a className="btn primary block" href={href('videos', row.clip_id)}>Review in Videos</a>
          )}
        </>
      )}
      more={keepable(row) || original ? (
        <>
          <KeepToggle row={row} />
          <OriginalLink url={row.url} />
        </>
      ) : undefined}
    />
  );
}
