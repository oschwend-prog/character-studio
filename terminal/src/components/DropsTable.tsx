// "Your drops" (owner 2026-10-06: "the core of the terminal is dropping our characters into my saved videos"): every dropped video,
// whatever its character, as a grid of big clip cards you can tap to watch (ClipCard, Task 11, owner 2026-10-08: "make them larger
// so I can actually see them"). Per card: the picture (the cover of the section, else its five-frame strip, else the drop's tile),
// the score, what is in it, the character, the section and its price, where it is (one plain chip: Adding, Checking, Pick a
// character, Ready, Making, Done, Blocked, Failed; lib/clipstatus.ts) and the buttons the drop card had: the character menu first
// for a Pick a character clip (the live roster, ★ on the one the check recommends, with its reason, which the owner may ignore:
// set_drop_character, migration 0013, then the free check again in that voice), then Make it (or Try again, or Review in Videos),
// and Adjust and Try again under it. More opens the rest of the card: the character menu, the five-frame strip, the facts, the
// moments with text on screen, own footage, Keep (a clip not made yet: retention never deletes a kept one), the original post and
// Remove (two steps: "Remove this clip? Yes, remove / Keep it").
// Nothing is paid before Make it. The Clips page passes the cards its filter keeps.
import { AlertTriangle } from 'lucide-react';
import { useEffect, useState, type ReactNode } from 'react';
import { cardPrice, originalLink, playableFor } from '../lib/clipcard';
import { CHIP_CLASS, CHIP_LABEL, characterConfirm, clipActions, clipChip, makeTotal } from '../lib/clipstatus';
import {
  PART_LABEL, RECOMMEND, avoidLabel, characterChoice, characterMenu, dropCredits, dropLine, dropTitle, effectiveDrop,
  isDropCard, recommendationLine, retryAdjust, sectionLabel, type CharacterMenu,
} from '../lib/drop';
import { formatCredits } from '../lib/format';
import { href } from '../lib/hooks';
import { scoreOf } from '../lib/ranking';
import { nameOf, type RosterEntry } from '../lib/roster';
import { useStudio } from '../lib/store';
import { trackerStep } from '../lib/tracker';
import type { Budget, DropAdjust, TrackerRow } from '../lib/types';
import { AdjustSheet } from './AdjustSheet';
import { ClipCard, ClipGrid, OriginalLink, RemoveClip, dropPicture } from './ClipCard';
import { KeepToggle } from './KeepToggle';
import { PickThumb } from './PickThumb';
import { Spinner } from './ui';

export function DropsTable({
  rows, roster, budget, now, summaryRows = rows, toolbar, empty,
}: {
  rows: ReadonlyArray<TrackerRow>;
  roster: ReadonlyArray<RosterEntry>;
  budget: Budget | null;
  now: number;
  /** The rows the "N to make · about X credits" line adds up: every drop, when `rows` is a filtered view of them. */
  summaryRows?: ReadonlyArray<TrackerRow>;
  /** Under the heading, above the cards: the Clips page's filter chips. */
  toolbar?: ReactNode;
  /** One line to say when there is no card (a filter that keeps none); the two-line "No drops yet" when absent. */
  empty?: string;
}) {
  const total = makeTotal(summaryRows, now);
  const left = budget ? Math.max(0, budget.cap - budget.committed) : null;

  return (
    <section className="stack" style={{ gap: 10 }} aria-labelledby="drops-title">
      <div>
        <h2 className="h2" id="drops-title">Your drops</h2>
        <p className="small muted num" style={{ margin: '6px 0 0' }}>
          {total.count === 0
            ? 'Nothing to make yet.'
            : `${total.count} to make · about ${formatCredits(total.credits)}`}
          {left != null && ` · ${formatCredits(left)} left of this month’s ${formatCredits(budget!.cap)} cap`}
        </p>
      </div>
      {toolbar}
      {rows.length === 0 ? (
        <div className="panel empty">
          {empty ? (
            <span className="muted small">{empty}</span>
          ) : (
            <>
              <b>No drops yet.</b>
              <span className="muted small">Drop a video above: it is checked for free, and the studio recommends the character.</span>
            </>
          )}
        </div>
      ) : (
        <ClipGrid label={`Your drops, ${rows.length}, the newest first`}>
          {rows.map((r) => (
            <DropItem key={r.pick_id} row={r} roster={roster} now={now} />
          ))}
        </ClipGrid>
      )}
    </section>
  );
}

/** The preview still: the middle frame of the five-frame strip of the section (a signed URL), else the drop's tile. Today's
 * Approve these uses it for a finished video's picture. */
export function DropThumb({ row }: { row: TrackerRow }) {
  const { backend } = useStudio();
  const path = row.drop_card?.preview_path ?? null;
  const [src, setSrc] = useState<string | null>(null);
  useEffect(() => {
    let live = true;
    setSrc(null);
    if (path) void backend.previewUrl(path).then((u) => live && setSrc(u));
    return () => {
      live = false;
    };
  }, [backend, path]);
  if (!src) return <PickThumb pick={row} size="small" />;
  return (
    <div className="thumb small tall">
      <img src={src} alt={`A frame of ${dropTitle(row)}`} loading="lazy" decoding="async" />
    </div>
  );
}

function DropItem({ row, roster, now }: { row: TrackerRow; roster: ReadonlyArray<RosterEntry>; now: number }) {
  const { backend, run, busy } = useStudio();
  const d = row.drop_card!;
  const [adjusting, setAdjusting] = useState(false);
  const key = `drop-${row.pick_id}`;
  const charKey = `char-${row.pick_id}`;
  const changing = busy.has(charKey); // the character menu's own run: the buttons wait for it, without a spinner of their own
  const working = busy.has(key);
  const menu = characterMenu(row, roster);
  const actions = clipActions(row, now);
  const e = effectiveDrop(d, d.adjust ?? {});
  const priced = d.credits != null && d.window != null;
  const credits = priced ? dropCredits(d, d.adjust ?? {}) : null;
  const title = dropTitle(row);
  const score = scoreOf(row);
  const reason = score != null && typeof d.score?.reason === 'string' && d.score.reason.trim() ? d.score.reason.trim() : null;
  const pick = clipChip(row) === 'pick';
  const review = row.clip_state === 'awaiting_approval' && row.clip_id ? row.clip_id : null;
  const original = originalLink(row.url)?.url ?? null;

  const make = (adjust: DropAdjust | null) =>
    run(key, () => backend.requestJob(row.pick_id, 'make', adjust), `Make it: ${row.character_name ?? 'he'} is on his way (about ${dropCredits(d, adjust ?? {})} credits)`);
  const recheck = () => run(key, () => backend.requestJob(row.pick_id, 'process'), 'Checking it again');
  const remove = () => run(key, () => backend.decidePick(row.pick_id, 'skip', 'removed by the owner from Clips', null), 'Removed');
  const choose = (slug: string) => {
    if (characterChoice(menu, row.character_slug, slug) === 'none') return;
    const name = roster.find((c) => c.slug === slug)?.name ?? slug;
    void run(
      charKey, () => backend.setDropCharacter(row.pick_id, slug),
      slug === row.character_slug ? `${name} it is` : `${name}: checking it again in his voice (free)`,
    );
  };
  // the one big button: Make it, else Try again after a failed Make it, else Review in Videos, else Try again of the check
  const main = actions.includes('make') ? 'make' : actions.includes('retry-make') ? 'retry-make' : review ? 'review' : actions.includes('retry-check') ? 'retry-check' : null;
  const cell = (prefix: string) => (
    <CharacterCell row={row} menu={menu} confirm={characterConfirm(row, roster)} working={working || changing} onChoose={choose} idPrefix={prefix} />
  );

  return (
    <>
      <ClipCard
        id={`a-${row.pick_id}`} title={title} picture={dropPicture(row, title)} playable={playableFor(row)}
        score={score ?? undefined} scoreTitle="The free check’s score: how likely the clip gets views with him in it" reason={reason}
        price={priced ? cardPrice(credits, e.length_s) : d.state === 'checking' || d.state === 'uploading' ? 'priced by the check' : undefined}
        sheetPrice={priced ? `about ${credits} credits · ${sectionLabel(e.start_s, e.length_s)}` : undefined}
        character={row.character_slug ? `For ${row.character_name ?? nameOf(row.character_slug)}` : 'No character yet'}
        dataChar={row.character_slug ?? 'none'} original={original}
        extra={
          <>
            <span className="small muted">
              {d.star?.description ? `${d.window ? 'Replaces' : 'Star:'} ${e.star}` : d.kind === 'link' ? row.creator_handle ?? 'a link' : 'your video'}
            </span>
            <StatusCell row={row} now={now} />
          </>
        }
        action={({ where }) => (
          <>
            {pick && <div className="needs-choice">{cell(where === 'sheet' ? 'pl-char' : 'dt-char')}</div>}
            {main === 'make' && (
              <button type="button" className="btn primary block" disabled={working || changing} aria-busy={working} onClick={() => void make(null)}>
                {working && <Spinner />} Make it
              </button>
            )}
            {main === 'retry-make' && (
              <button type="button" className="btn primary block" disabled={working || changing} aria-busy={working} onClick={() => void make(retryAdjust(d))}>
                {working && <Spinner />} Try again · <span className="num">about {dropCredits(d, d.adjust ?? {})}</span>
              </button>
            )}
            {main === 'review' && (
              <a className="btn primary block" href={href('videos', review!)}>
                Review in Videos
              </a>
            )}
            {main === 'retry-check' && (
              <button type="button" className="btn line block" disabled={working || changing} onClick={() => void recheck()}>
                Try again
              </button>
            )}
          </>
        )}
        links={
          actions.includes('adjust') || (actions.includes('retry-check') && main !== 'retry-check') ? (
            <>
              {actions.includes('adjust') && (
                <button type="button" className="cc-textlink" disabled={working || changing} onClick={() => setAdjusting(true)}>
                  Adjust
                </button>
              )}
              {actions.includes('retry-check') && main !== 'retry-check' && (
                <button type="button" className="cc-textlink" disabled={working || changing} onClick={() => void recheck()}>
                  Try again
                </button>
              )}
            </>
          ) : undefined
        }
        more={
          <DropDetail
            row={row} character={pick ? null : cell('dt-char')}
            remove={actions.includes('remove') ? { disabled: working || changing, run: () => void remove() } : null}
          />
        }
      />
      {adjusting && (
        <AdjustSheet
          row={row}
          onClose={() => setAdjusting(false)}
          onMake={async (adjust) => {
            const ok = await make(adjust);
            if (ok) setAdjusting(false);
          }}
          working={working}
        />
      )}
    </>
  );
}

/** A line that opens with the studio's ★: the star is decoration (`aria-hidden`), so a screen reader does not read "black star". */
function WithStar({ text }: { text: string }) {
  return text.startsWith('★ ') ? (
    <>
      <span aria-hidden="true">★</span> {text.slice(2)}
    </>
  ) : (
    <>{text}</>
  );
}

/** The character menu of a clip (★ on the recommended one, "Use <him>" for a Pick a character clip): also Clips by character's
 * Needs you. */
export function CharacterCell({
  row, menu, confirm, working, onChoose, idPrefix = 'dt-char',
}: {
  row: TrackerRow;
  menu: CharacterMenu;
  confirm: { slug: string; name: string } | null;
  working: boolean;
  onChoose(slug: string): void;
  /** Its ids' prefix: the player sheet draws the same menu while the card's is in the page. */
  idPrefix?: string;
}) {
  const line = recommendationLine(menu, row.character_slug);
  const id = `${idPrefix}-${row.pick_id}`;
  return (
    <span className="stack" style={{ gap: 4 }}>
      <label className="sr-only" htmlFor={id}>Character for {dropTitle(row)}</label>
      <select
        id={id} className="select" value={menu.value} disabled={menu.locked || working}
        aria-describedby={line ? `${id}-why` : undefined} onChange={(e) => onChoose(e.target.value)}
      >
        {menu.pending && <option value={RECOMMEND}>★ Recommend</option>}
        {menu.options.map((o) => (
          <option key={o.slug} value={o.slug} disabled={o.disabled}>
            {o.label}
          </option>
        ))}
      </select>
      {confirm && (
        <button type="button" className="btn line" disabled={working} onClick={() => onChoose(confirm.slug)}>
          Use {confirm.name}
        </button>
      )}
      {line && (
        <span className="hint" id={`${id}-why`}>
          <WithStar text={line} />
        </span>
      )}
    </span>
  );
}

function StatusCell({ row, now }: { row: TrackerRow; now: number }) {
  const d = row.drop_card!;
  const chip = clipChip(row);
  const pill = (
    <span><span className={`drop-state ${CHIP_CLASS[chip]}`}>{CHIP_LABEL[chip]}</span></span>
  );
  if (!isDropCard(row) && row.clip_state != null) {
    // Make it was tapped and the clip exists: the chip says where it is; the step's own note or reason goes under it
    const s = trackerStep(row, now);
    return (
      <span className="stack cc-status" style={{ gap: 4 }}>
        {pill}
        {s.reason ? (
          <span className={`small ${s.state === 'failed' ? 'error-text' : 'muted'}`}>{s.reason}</span>
        ) : s.note ? (
          <span className="small muted">{s.note}</span>
        ) : null}
      </span>
    );
  }
  const attached = Boolean(row.owner_clip_path); // the file is saved (the clips folder): waiting for the check, not a lost upload
  const flagged = d.state === 'blocked' || d.state === 'failed' || d.state === 'waiting';
  const moving = d.state === 'uploading' || d.state === 'checking' || d.state === 'making';
  return (
    <span className="stack cc-status" style={{ gap: 4 }}>
      {pill}
      {flagged ? (
        <span className={`small ${d.state === 'waiting' ? 'muted' : 'error-text'}`} role={d.state === 'failed' ? 'alert' : undefined}>
          {d.state !== 'waiting' && <AlertTriangle size={13} aria-hidden="true" style={{ verticalAlign: '-2px', marginRight: 4 }} />}
          {dropLine(d, now, attached)}
        </span>
      ) : moving || d.reason ? (
        <span className="small muted">
          {moving && <Spinner />} {dropLine(d, now, attached)}
        </span>
      ) : null}
    </span>
  );
}

/** Under More: the character menu (when it is not the card's own action), what the drop card showed (the strip of the section, the
 * facts, the moments with text, own footage), Keep and the original post. */
function DropDetail({ row, character, remove }: { row: TrackerRow; character: ReactNode; remove: { disabled: boolean; run(): void } | null }) {
  const { backend, run, busy } = useStudio();
  const d = row.drop_card!;
  const key = `drop-${row.pick_id}`;
  const working = busy.has(key);
  const [strip, setStrip] = useState<string | null>(null);
  const e = effectiveDrop(d, d.adjust ?? {});
  const own = d.own_footage === true;
  const avoid = avoidLabel(d);

  useEffect(() => {
    let live = true;
    setStrip(null);
    if (d.preview_path) void backend.previewUrl(d.preview_path).then((u) => live && setStrip(u));
    return () => {
      live = false;
    };
  }, [backend, d.preview_path]);

  const setFootage = (value: boolean) => {
    if (value !== own) void run(key, () => backend.setDropFootage(row.pick_id, value), value ? 'Marked as your own footage' : 'Marked as a downloaded clip');
  };

  return (
    <div className="dt-detail" id={`dt-detail-${row.pick_id}`}>
      {character}
      {strip && (
        <div className="drop-strip">
          <img src={strip} alt={`Five frames of the section ${e.start_s}-${e.start_s + e.length_s} s`} loading="lazy" decoding="async" />
        </div>
      )}
      {d.window && (
        <dl className="drop-facts">
          <div><dt>Replaces</dt><dd>{e.star}</dd></div>
          <div><dt>His part</dt><dd>{PART_LABEL[e.part]}{e.gadgets.length ? ` · ${e.gadgets.join(', ')}` : ''}</dd></div>
          <div><dt>Section</dt><dd className="num">{sectionLabel(e.start_s, e.length_s)}{e.crop_x != null ? ' · cropped to 9:16' : ''}</dd></div>
          <div><dt>Hook</dt><dd>“{e.hook}”</dd></div>
        </dl>
      )}
      {avoid && <p className="hint" style={{ margin: 0 }}>Seen: {avoid}. Only the section is judged: it keeps clear of them.</p>}
      <div className="drop-footage" role="group" aria-label="Where the video comes from">
        <div className="seg">
          <button type="button" aria-pressed={!own} disabled={working} onClick={() => setFootage(false)}>
            Downloaded clip
          </button>
          <button type="button" aria-pressed={own} disabled={working} onClick={() => setFootage(true)}>
            Own footage
          </button>
        </div>
        <span className="hint">Own footage: your recording, or footage you may use. For the records; it does not change the video.</span>
      </div>
      <KeepToggle row={row} idPrefix="dt-keep" />
      <OriginalLink url={row.url} />
      {remove && <RemoveClip title={dropTitle(row)} disabled={remove.disabled} onRemove={remove.run} />}
    </div>
  );
}
