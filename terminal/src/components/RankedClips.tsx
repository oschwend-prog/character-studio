// The saved clips ranked (terminal v3, spec 5.2 and 6). Two lists. `AvailableClips` is the New clips page's (owner 2026-10-15):
// every clip not made yet under one filter (All, Needs a character, one chip per live character), Needs a character first, then
// Ready ranked 1, 2, 3... by score with the score, the one-line reason, the price and a Top pick badge on the first three scored
// ones (an unscored clip is "not scored yet"), Who (the character menu), How (what Make it makes) with Adjust, and ＋ Add (the tick
// the Make bar adds up; nothing is spent before its confirm); then what is being checked, the blocked and failed in one closed row.
// A made clip has left: Videos › Making. Every clip is a big card you can tap to watch (ClipCard, Task 11, owner 2026-10-08); under
// More, "Use for another character" (a version for a like-for-like character, free: studio.copy_drop), Keep and the original post.
// `RankedClips` is Today's "Make these": his top 3 Ready clips and, when he has one, an Explore clip (one suggestion in four,
// learning test A).
import { ArrowRight, CircleAlert } from 'lucide-react';
import { useMemo, useState } from 'react';
import { cardPrice, originalLink, playableFor } from '../lib/clipcard';
import { CHIP_CLASS, CHIP_LABEL, characterConfirm, clipChip } from '../lib/clipstatus';
import { cantUseLine, clipsByCharacter, isTopPick, readyWithChoice, versionsLine } from '../lib/clipsview';
import { PART_LABEL, characterChoice, characterMenu, dropCredits, dropLine, dropTitle, sectionLabel, effectiveDrop } from '../lib/drop';
import { keepable } from '../lib/hits';
import { href } from '../lib/hooks';
import { SOURCE_WORDS, availableClips, clipSource, type AvailableFilter } from '../lib/newclips';
import { reuseTargets, scoreOf, suggestedClips } from '../lib/ranking';
import { activeRoster, nameOf, type RosterEntry } from '../lib/roster';
import { useStudio } from '../lib/store';
import type { DropAdjust, TrackerRow } from '../lib/types';
import { rankOrderFor, scoreTestOf, type RankOrder } from '../lib/weekly';
import { AdjustSheet } from './AdjustSheet';
import { ClipCard, ClipGrid, MakeToggle, OriginalLink, dropPicture } from './ClipCard';
import { CharacterCell } from './DropsTable';
import { KeepToggle } from './KeepToggle';
import { Avatar, Spinner } from './ui';

const message = (e: unknown) => (e instanceof Error ? e.message : String(e));

const SCORE_TITLE = 'The free check’s score: how likely the clip gets views with him in it';

/**
 * How his ready clips are ranked: by the score, or, after the weekly review says the score test failed, by the freshness of the
 * trend first and the score second (learning plan 3.2). Today's Make these and the Clips page read the same answer.
 */
export function useRankOrder(): RankOrder {
  const { data } = useStudio();
  const weekly = data?.weekly;
  return useMemo(() => rankOrderFor(scoreTestOf(weekly)), [weekly]);
}

/** The check's one line why the clip may get views, shown only with its score. */
const scoreReason = (row: TrackerRow): string | null => {
  const r = row.drop_card?.score?.reason;
  return scoreOf(row) != null && typeof r === 'string' && r.trim() ? r.trim() : null;
};

export function RankedClips({
  rows, characters, ticked, onTick, compact = false,
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
  const order = useRankOrder();
  const { groups } = clipsByCharacter(rows, characters, order);
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
          const top = suggestedClips(g.ready, 3, order);
          return (
            <section key={g.slug} className={`pick-sec ${g.slug}`} aria-labelledby={`make-${g.slug}`}>
              <header className="pick-sec-head">
                <Avatar slug={g.slug} name={g.name} size={32} />
                <h3 className="h2" id={`make-${g.slug}`}>{g.name}</h3>
                <span className="small muted num sec-count">{readyWithChoice(g.ready.length, g.needsYou.length)}</span>
              </header>
              {top.length ? (
                <ClipGrid label={top.some((t) => t.explore) ? `${g.name}’s best ready clips, best first, and one below his median to try` : `${g.name}’s best ready clips, best first`}>
                  {top.map(({ row: r, explore }, i) => (
                    <ReadyCard key={r.pick_id} row={r} rank={explore ? null : i + 1} top={!explore && isTopPick(r, i)} explore={explore}
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

  return null; // the Clips page lists its clips with AvailableClips (owner 2026-10-15); RankedClips is Today's Make these
}

/**
 * The New clips page's list (owner 2026-10-15: "view video on page and decide for which character and how to generate"): every clip
 * not made yet, one list under a filter (All, Needs a character, one chip per live character; `?c=` in the address), Needs a
 * character first, then Ready best first (each card: watch it, Who, How with Adjust, the price and ＋ Add), then what is being
 * checked, the blocked and failed in one closed row. A clip whose Make it was sent leaves the list: Videos › Making has it.
 */
export function AvailableClips({
  rows, characters, filter, onFilter, ticked, onTick, now,
}: {
  rows: ReadonlyArray<TrackerRow>;
  /** The live characters, in the owner's order: one chip each. */
  characters: ReadonlyArray<{ slug: string; name: string }>;
  filter: AvailableFilter;
  onFilter(f: AvailableFilter): void;
  ticked: ReadonlySet<string>;
  onTick(id: string, on: boolean): void;
  now: number;
}) {
  const { data } = useStudio();
  const order = useRankOrder();
  const roster = activeRoster(data?.characters);
  const names = new Map((data?.characters ?? []).map((c) => [c.slug, c.name]));
  const hitUrls = new Set((data?.hits ?? []).map((h) => h.url));
  const a = availableClips(rows, characters, filter, order);
  const chips: Array<{ id: AvailableFilter; label: string; needs?: boolean }> = [
    { id: 'all', label: 'All' },
    ...(a.counts.needs ? [{ id: 'needs', label: 'Needs a character', needs: true }] : []),
    ...characters.map((c) => ({ id: c.slug, label: c.name })),
  ];
  const nothing = !a.needsWho.length && !a.ready.length && !a.checking.length && !a.problems.length;
  return (
    <section className="avail stack" id="avail" aria-labelledby="avail-title">
      <header className="avail-head">
        <h2 className="h2" id="avail-title">Available clips <span className="count">{a.counts.all}</span></h2>
        <span className="small muted">best first</span>
      </header>
      <nav className="char-jump" aria-label="Show the clips of">
        {chips.map((c) => (
          <button
            key={c.id} type="button" className="chip" aria-pressed={filter === c.id}
            onClick={(e) => {
              e.currentTarget.scrollIntoView({ inline: 'nearest', block: 'nearest' }); // a chip half off the row comes into view
              onFilter(c.id);
            }}
          >
            {c.label} <span className={`num jump-count${c.needs ? ' jump-needs' : ''}`}>{a.counts[c.id] ?? 0}</span>
          </button>
        ))}
      </nav>

      {nothing && (
        <p className="small muted pick-sec-empty">
          {filter === 'all' ? 'No clips waiting. Save a video to the clips folder, add a link above or use a hit from the social scan.'
            : 'Nothing here. Choose All to see every clip.'}
        </p>
      )}

      {a.needsWho.length > 0 && (
        <div className="pick-group">
          <h3 className="pick-group-head">Needs a character <span className="count">{a.needsWho.length}</span></h3>
          <ClipGrid label={`Clips that need a character, ${a.needsWho.length}`}>
            {a.needsWho.map((r) => (clipChip(r) === 'pick'
              ? <NeedsYouCard key={r.pick_id} row={r} roster={roster} />
              : <QuietCard key={r.pick_id} row={r} now={now} versions={null} />))}
          </ClipGrid>
        </div>
      )}

      {a.ready.length > 0 && (
        <div className="pick-group">
          <h3 className="pick-group-head">Ready to make <span className="count">{a.ready.length}</span></h3>
          <ClipGrid label="Clips ready to make, best first">
            {a.ready.map((r, i) => (
              <ReadyCard key={r.pick_id} row={r} rank={i + 1} top={isTopPick(r, i)} ticked={ticked.has(r.pick_id)} onTick={onTick}
                versions={versionsLine(r, data?.tracker ?? rows, names)} roster={roster} source={SOURCE_WORDS[clipSource(r, hitUrls)]}
/>
            ))}
          </ClipGrid>
        </div>
      )}

      {a.checking.length > 0 && (
        <div className="pick-group">
          <h3 className="pick-group-head">Being checked <span className="count">{a.checking.length}</span></h3>
          <ClipGrid label="Clips being checked">
            {a.checking.map((r) => <QuietCard key={r.pick_id} row={r} now={now} versions={versionsLine(r, data?.tracker ?? rows, names)} />)}
          </ClipGrid>
        </div>
      )}

      {a.problems.length > 0 && (
        <details className="cant-use">
          <summary>
            <CircleAlert size={15} aria-hidden="true" /> {cantUseLine(a.problems.length)}
          </summary>
          <ul className="cant-use-list">
            {a.problems.map((r) => (
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

      {a.others > 0 && filter === 'all' && (
        <p className="small muted" style={{ margin: 0 }}>
          {a.others === 1 ? '1 clip has' : `${a.others} clips have`} no live character (none chosen yet, or a paused one):{' '}
          <a href={href('clips', undefined, { v: 'all' })}>see All clips</a>.
        </p>
      )}
    </section>
  );
}

/** A Ready clip: its card with the rank, Top pick, score and reason, price and section, and the Make toggle (the tick the Make bar
 * adds up); the versions line; under More, "Use for another character", Keep and the original post (not in compact). */
function ReadyCard({
  row, rank, top, explore = false, ticked, onTick, versions, compact = false, roster, source,
}: {
  row: TrackerRow;
  rank: number | null; // null for the Explore clip: its real rank is lower, and the card says why it is there
  top: boolean;
  explore?: boolean;
  ticked: boolean;
  onTick(id: string, on: boolean): void;
  versions: string | null;
  compact?: boolean;
  /** New clips (owner 2026-10-15): the card decides who and how. With the roster, Who (the character menu: another one checks it
   * again in his voice, free) and How (what Make it makes, with Adjust: the section, his part, the gadgets, the hook). */
  roster?: ReadonlyArray<RosterEntry>;
  /** Where the clip came from (lib/newclips.ts SOURCE_WORDS). */
  source?: string;
}) {
  const { data, backend, run, busy } = useStudio();
  const [adjusting, setAdjusting] = useState(false);
  const d = row.drop_card!;
  const title = dropTitle(row);
  const priced = d.credits != null;
  const credits = priced ? dropCredits(d, d.adjust ?? {}) : null;
  const e = effectiveDrop(d, d.adjust ?? {});
  const original = originalLink(row.url)?.url ?? null;
  const more = !compact && (keepable(row) || original != null || reuseTargets(row, data?.characters ?? [], data?.tracker ?? []).length > 0);
  const key = `drop-${row.pick_id}`;
  const charKey = `char-${row.pick_id}`;
  const menu = roster ? characterMenu(row, roster) : null;
  const choose = (slug: string) => {
    if (!menu || !roster || characterChoice(menu, row.character_slug, slug) === 'none') return;
    const name = roster.find((c) => c.slug === slug)?.name ?? slug;
    void run(charKey, () => backend.setDropCharacter(row.pick_id, slug), `${name}: checking it again in his voice (free)`);
  };
  const make = (adjust: DropAdjust) =>
    run(key, () => backend.requestJob(row.pick_id, 'make', adjust), `Make it: ${row.character_name ?? 'he'} is on his way (about ${dropCredits(d, adjust)} credits)`);
  return (
    <>
      <ClipCard
        id={`${compact ? 'c' : 'f'}-${row.pick_id}`} title={title} picture={dropPicture(row, title)} playable={playableFor(row)}
        rank={rank} top={top} explore={explore} score={scoreOf(row)} scoreTitle={SCORE_TITLE} checkScore reason={scoreReason(row)}
        price={cardPrice(credits, d.window ? e.length_s : null)}
        sheetPrice={credits != null ? `about ${credits} credits${d.window ? ` · ${sectionLabel(e.start_s, e.length_s)}` : ''}` : 'priced by the check'}
        extra={(versions || source || roster) && (
          <>
            {roster && <span className="small muted cc-how">How: {PART_LABEL[e.part].toLowerCase()} part · {sectionLabel(e.start_s, e.length_s)}</span>}
            {source && <span className="small muted">{source}</span>}
            {versions && <span className="small muted">{versions}</span>}
          </>
        )}
        ticked={ticked} dataChar={row.character_slug ?? 'none'} original={original}
        action={({ describedBy, where }) => (
          <>
            {menu && (
              <div className="needs-choice">
                <CharacterCell row={row} menu={menu} confirm={null} working={busy.has(charKey) || busy.has(key)} onChoose={choose}
                  idPrefix={where === 'sheet' ? 'pl-who' : 'av-who'} why={false} />
              </div>
            )}
            <MakeToggle ticked={ticked} disabled={!priced} onToggle={(on) => onTick(row.pick_id, on)} describedBy={describedBy} />
          </>
        )}
        links={roster && priced ? (
          <button type="button" className="cc-textlink" disabled={busy.has(key)} onClick={() => setAdjusting(true)}>
            Adjust how
          </button>
        ) : undefined}
        more={more ? (
          <>
            <ReuseMenu row={row} title={title} />
            <KeepToggle row={row} />
            <OriginalLink url={row.url} />
          </>
        ) : undefined}
      />
      {adjusting && (
        <AdjustSheet
          row={row}
          onClose={() => setAdjusting(false)}
          onMake={async (adjust) => {
            const ok = await make(adjust);
            if (ok) setAdjusting(false);
          }}
          working={busy.has(key)}
        />
      )}
    </>
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
      score={score ?? undefined} scoreTitle={SCORE_TITLE} checkScore reason={scoreReason(row)}
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
