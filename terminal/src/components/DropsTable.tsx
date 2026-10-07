// "Your drops" (owner 2026-10-06: "the core of the terminal is dropping our characters into my saved videos"): every dropped video
// in one table, whatever its character, in the Long list's table look (on a phone each row stacks). Per row: the preview still,
// what is in it, the character menu (the live roster, ★ on the one the check recommends, with its reason, which the owner may
// ignore: set_drop_character, migration 0013, then the free check again in that voice), the section and its price, where it is
// (one plain chip: Adding, Checking, Pick a character, Ready, Making, Done, Blocked, Failed; lib/clipstatus.ts), and the buttons the
// drop card had (Make it, Adjust, Try again, Remove). The chevron opens the rest of the card: the five-frame strip, the facts, the
// moments with text on screen, own footage. Nothing is paid before Make it. The Clips page passes the rows its filter keeps.
import { AlertTriangle, ChevronRight, SlidersHorizontal } from 'lucide-react';
import { Fragment, useEffect, useState, type ReactNode } from 'react';
import { CHIP_CLASS, CHIP_LABEL, clipActions, clipChip, makeTotal } from '../lib/clipstatus';
import {
  PART_LABEL, RECOMMEND, avoidLabel, characterMenu, dropCredits, dropLine, dropTitle, effectiveDrop,
  isDropCard, recommendationLine, sectionLabel, type CharacterMenu,
} from '../lib/drop';
import { formatCredits } from '../lib/format';
import { href } from '../lib/hooks';
import type { RosterEntry } from '../lib/roster';
import { useStudio } from '../lib/store';
import { trackerStep } from '../lib/tracker';
import type { Budget, DropAdjust, TrackerRow } from '../lib/types';
import { AdjustSheet } from './AdjustSheet';
import { PickThumb } from './PickThumb';
import { Spinner } from './ui';

const COLUMNS = 6;

export function DropsTable({
  rows, roster, budget, now, summaryRows = rows, toolbar, empty,
}: {
  rows: ReadonlyArray<TrackerRow>;
  roster: ReadonlyArray<RosterEntry>;
  budget: Budget | null;
  now: number;
  /** The rows the "N to make · about X credits" line adds up: every drop, when `rows` is a filtered view of them. */
  summaryRows?: ReadonlyArray<TrackerRow>;
  /** Under the heading, above the table: the Clips page's filter chips. */
  toolbar?: ReactNode;
  /** One line to say when there is no row (a filter that keeps none); the two-line "No drops yet" when absent. */
  empty?: string;
}) {
  const [open, setOpen] = useState<ReadonlySet<string>>(new Set());
  const total = makeTotal(summaryRows, now);
  const left = budget ? Math.max(0, budget.cap - budget.committed) : null;
  const toggle = (id: string) =>
    setOpen((s) => {
      const next = new Set(s);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });

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
        <div className="panel ll-scroll" role="region" aria-label={`Your drops, ${rows.length}`} tabIndex={0}>
          <table className="ll-table drops-table">
            <caption className="sr-only">Every video you dropped, the newest first.</caption>
            <thead>
              <tr>
                <th scope="col" className="ll-pic"><span className="sr-only">Picture</span></th>
                <th scope="col" className="ll-clip"><span className="label">What’s in it</span></th>
                <th scope="col" className="dt-char"><span className="label">Character</span></th>
                <th scope="col" className="dt-price"><span className="label">Section · price</span></th>
                <th scope="col" className="dt-state"><span className="label">Status</span></th>
                <th scope="col" className="dt-actions"><span className="sr-only">Actions</span></th>
              </tr>
            </thead>
            <tbody>
              {rows.map((r) => (
                <Fragment key={r.pick_id}>
                  <DropRow row={r} roster={roster} now={now} expanded={open.has(r.pick_id)} onToggle={() => toggle(r.pick_id)} />
                  {open.has(r.pick_id) && <DropDetail row={r} />}
                </Fragment>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}

/** The preview still: the middle frame of the five-frame strip of the section (a signed URL), else the drop's tile. */
function DropThumb({ row }: { row: TrackerRow }) {
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

function DropRow({
  row, roster, now, expanded, onToggle,
}: { row: TrackerRow; roster: ReadonlyArray<RosterEntry>; now: number; expanded: boolean; onToggle(): void }) {
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
  const title = dropTitle(row);
  const detailId = `dt-detail-${row.pick_id}`;

  const make = (adjust: DropAdjust | null) =>
    run(key, () => backend.requestJob(row.pick_id, 'make', adjust), `Make it: ${row.character_name ?? 'he'} is on his way (about ${dropCredits(d, adjust ?? {})} credits)`);
  const recheck = () => run(key, () => backend.requestJob(row.pick_id, 'process'), 'Checking it again');
  const remove = () => run(key, () => backend.decidePick(row.pick_id, 'skip', 'removed by the owner from In the works', null), 'Removed');
  const choose = (slug: string) => {
    if (slug === RECOMMEND || (slug === row.character_slug && menu.by === 'owner')) return;
    const name = roster.find((c) => c.slug === slug)?.name ?? slug;
    void run(
      charKey, () => backend.setDropCharacter(row.pick_id, slug),
      slug === row.character_slug ? `${name} it is` : `${name}: checking it again in his voice (free)`,
    );
  };

  return (
    <tr className="ll-row" data-char={row.character_slug ?? 'none'} data-drop={d.state}>
      <td className="ll-pic">
        <DropThumb row={row} />
      </td>
      <th scope="row" className="ll-clip">
        <div className="ll-clip-in">
          <button
            type="button" className="ll-chev" aria-expanded={expanded} aria-controls={expanded ? detailId : undefined}
            aria-label={expanded ? 'Hide the details' : 'Show the details: the frames, the hook, own footage'} onClick={onToggle}
          >
            <ChevronRight size={15} aria-hidden="true" />
          </button>
          <span className="stack" style={{ gap: 2 }}>
            <span className="ll-title">{title}</span>
            <span className="small muted">
              {d.star?.description
                ? `${d.window ? 'Replaces' : 'Star:'} ${e.star}`
                : d.kind === 'link' ? row.creator_handle ?? 'a link' : 'your video'}
            </span>
          </span>
        </div>
      </th>
      <td className="dt-char">
        <CharacterCell row={row} menu={menu} working={working || changing} onChoose={choose} />
      </td>
      <td className="dt-price">
        {priced ? (
          <span className="stack" style={{ gap: 2 }}>
            <b className="num">about {dropCredits(d, d.adjust ?? {})} credits</b>
            <span className="small muted num">{sectionLabel(e.start_s, e.length_s)}</span>
          </span>
        ) : d.state === 'checking' || d.state === 'uploading' ? (
          <span className="faint small">priced by the check</span>
        ) : null}
      </td>
      <td className="dt-state">
        <StatusCell row={row} now={now} />
      </td>
      <td className="dt-actions">
        <div className="drop-actions">
          {actions.includes('make') && (
            <button type="button" className="btn primary" disabled={working || changing} aria-busy={working} onClick={() => void make(null)}>
              {working && <Spinner />} Make it
            </button>
          )}
          {actions.includes('adjust') && (
            <button type="button" className="btn ghost" disabled={working || changing} onClick={() => setAdjusting(true)}>
              <SlidersHorizontal aria-hidden="true" /> Adjust
            </button>
          )}
          {actions.includes('retry-make') && (
            <button type="button" className="btn primary" disabled={working || changing} aria-busy={working} onClick={() => void make(null)}>
              {working && <Spinner />} Try again · <span className="num">about {dropCredits(d, d.adjust ?? {})}</span>
            </button>
          )}
          {actions.includes('retry-check') && (
            <button type="button" className="btn line" disabled={working || changing} onClick={() => void recheck()}>
              Try again
            </button>
          )}
          {actions.includes('remove') && (
            <button type="button" className="btn ghost" disabled={working || changing} onClick={() => void remove()}>
              Remove
            </button>
          )}
          {row.clip_state === 'awaiting_approval' && row.clip_id && (
            <a className="btn primary" href={href('videos', row.clip_id)}>
              Review in Queue
            </a>
          )}
        </div>
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
      </td>
    </tr>
  );
}

function CharacterCell({
  row, menu, working, onChoose,
}: { row: TrackerRow; menu: CharacterMenu; working: boolean; onChoose(slug: string): void }) {
  const line = recommendationLine(menu, row.character_slug);
  const id = `dt-char-${row.pick_id}`;
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
      {line && (
        <span className="hint" id={`${id}-why`}>
          {line}
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
      <span className="stack" style={{ gap: 4 }}>
        {pill}
        {s.reason ? (
          <span className={`small ${s.state === 'failed' ? 'error-text' : 'muted'}`}>{s.reason}</span>
        ) : s.note ? (
          <span className="small muted">{s.note}</span>
        ) : null}
      </span>
    );
  }
  const flagged = d.state === 'blocked' || d.state === 'failed' || d.state === 'waiting';
  const moving = d.state === 'uploading' || d.state === 'checking' || d.state === 'making';
  return (
    <span className="stack" style={{ gap: 4 }}>
      {pill}
      {flagged ? (
        <span className={`small ${d.state === 'waiting' ? 'muted' : 'error-text'}`} role={d.state === 'failed' ? 'alert' : undefined}>
          {d.state !== 'waiting' && <AlertTriangle size={13} aria-hidden="true" style={{ verticalAlign: '-2px', marginRight: 4 }} />}
          {dropLine(d, now)}
        </span>
      ) : moving || d.reason ? (
        <span className="small muted">
          {moving && <Spinner />} {dropLine(d, now)}
        </span>
      ) : null}
    </span>
  );
}

/** Under a row: what the drop card showed (the strip of the section, the facts, the moments with text, own footage). */
function DropDetail({ row }: { row: TrackerRow }) {
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
    <tr className="ll-detail" id={`dt-detail-${row.pick_id}`}>
      <td colSpan={COLUMNS}>
        <div className="ll-detail-in">
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
        </div>
      </td>
    </tr>
  );
}
