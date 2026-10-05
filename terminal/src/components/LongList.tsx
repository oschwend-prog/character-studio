// The Picks page's "Long list": every proposed pick in one sortable table, to decide which clips post first. Filter chips for the
// character and the category, a tap on a column header sorts (again: the other way), a tap on a row opens the pick itself (the same
// card, Make it and Skip as on the Cards view: there is no other way to approve), the chevron shows the analyst's reasoning and
// checks under the row. On a phone the picture and the clip stay put while the numbers scroll sideways inside the card.
import { ChevronDown, ChevronRight, ChevronUp, ExternalLink } from 'lucide-react';
import { Fragment, useMemo, useState, type KeyboardEvent, type MouseEvent } from 'react';
import {
  DEFAULT_SORT, LONG_LIST_COLUMNS, ariaSort, compactCount, longListCounts, longListRows, nextSort, outlierCell, perDay, scoreCell,
  sortLongList, type LongListRow, type LongListSort,
} from '../lib/longlist';
import { TIERS, TIER_HINTS, TIER_LABELS } from '../lib/rules';
import type { Pick, Tier } from '../lib/types';
import { PickThumb } from './PickThumb';
import { Livery } from './ui';

const MODE_LABEL = { dropin: 'Drop-in', recreate: 'Recreate' } as const;
const COLUMN_COUNT = LONG_LIST_COLUMNS.length + 1; // the picture, then the sortable ones

export function LongList({
  picks, roster, character, onCharacter, now, onOpen,
}: {
  picks: ReadonlyArray<Pick>;
  roster: ReadonlyArray<{ slug: string; name: string }>;
  character: string;
  onCharacter(v: string): void;
  now: number;
  onOpen(pick: Pick): void;
}) {
  const [tier, setTier] = useState<Tier | 'all'>('all');
  const [sort, setSort] = useState<LongListSort>(DEFAULT_SORT);
  const [open, setOpen] = useState<ReadonlySet<string>>(new Set());
  const counts = useMemo(() => longListCounts(picks, character, roster, now), [picks, character, roster, now]);
  const rows = useMemo(() => sortLongList(longListRows(picks, { character, tier }, now), sort), [picks, character, tier, now, sort]);

  const toggle = (id: string) =>
    setOpen((s) => {
      const next = new Set(s);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  // a tap anywhere on the row opens the pick, unless it was on its own link or button
  const onRowClick = (e: MouseEvent<HTMLTableRowElement>, pick: Pick) => {
    if ((e.target as HTMLElement).closest('a, button')) return;
    onOpen(pick);
  };
  const onRowKey = (e: KeyboardEvent<HTMLTableRowElement>, pick: Pick) => {
    if (e.target !== e.currentTarget) return;
    if (e.key === 'Enter' || e.key === ' ') {
      e.preventDefault();
      onOpen(pick);
    }
  };

  return (
    <section className="longlist stack" style={{ gap: 12 }} aria-labelledby="longlist-title">
      <h2 className="sr-only" id="longlist-title">Long list</h2>
      <div className="stack" style={{ gap: 8 }}>
        <div className="chips ll-chips" role="group" aria-label="Character">
          {[...roster.map((c) => ({ id: c.slug, label: c.name })), { id: 'all', label: 'All' }].map((o) => (
            <button key={o.id} type="button" className="chip" aria-pressed={character === o.id} onClick={() => onCharacter(o.id)}>
              {o.label} <span className="num count">{counts.characters[o.id] ?? 0}</span>
            </button>
          ))}
        </div>
        <div className="chips tier-chips" role="group" aria-label="Category">
          {(['all', ...TIERS] as const).map((t) => (
            <button key={t} type="button" className={`chip tier-${t}`} aria-pressed={tier === t} onClick={() => setTier(t)} title={t === 'all' ? undefined : TIER_HINTS[t]}>
              {t === 'all' ? 'All' : TIER_LABELS[t]} <span className="num count">{counts.tiers[t]}</span>
            </button>
          ))}
        </div>
      </div>

      {rows.length === 0 ? (
        <div className="panel empty">
          <b>No picks here</b>
          <span className="muted small">Nothing proposed matches these filters. The daily scan files more.</span>
        </div>
      ) : (
        <div className="panel ll-scroll" role="region" aria-label={`Long list, ${rows.length} picks`} tabIndex={0}>
          <table className="ll-table">
            <caption className="sr-only">
              Proposed picks. {sort.key === 'default' ? 'Sorted by category, then recognisability and score.' : `Sorted by ${LONG_LIST_COLUMNS.find((c) => c.key === sort.key)?.label}.`} Select a row to open the pick.
            </caption>
            <thead>
              <tr>
                <th scope="col" className="ll-pic">
                  <span className="sr-only">Picture</span>
                </th>
                {LONG_LIST_COLUMNS.map((c) => {
                  const state = ariaSort(sort, c.key);
                  const Arrow = state === 'ascending' ? ChevronUp : ChevronDown;
                  return (
                    <th
                      key={c.key}
                      scope="col"
                      aria-sort={state}
                      className={`ll-${c.key}${c.numeric ? ' ll-n' : ''}${state !== 'none' ? ' sorted' : ''}`}
                      title={c.title}
                    >
                      <button type="button" className="ll-sort" onClick={() => setSort((s) => nextSort(s, c.key))}>
                        {c.label}
                        <Arrow size={13} aria-hidden="true" className={state === 'none' ? 'idle' : undefined} />
                      </button>
                    </th>
                  );
                })}
              </tr>
            </thead>
            <tbody>
              {rows.map((r) => (
                <Fragment key={r.pick.id}>
                  <Row row={r} expanded={open.has(r.pick.id)} onToggle={() => toggle(r.pick.id)} onClick={onRowClick} onKey={onRowKey} />
                  {open.has(r.pick.id) && <Detail row={r} onOpen={onOpen} />}
                </Fragment>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {sort.key !== 'default' && rows.length > 0 && (
        <button type="button" className="btn ghost ll-reset" onClick={() => setSort(DEFAULT_SORT)}>
          Back to the default order
        </button>
      )}
    </section>
  );
}

function Row({
  row: r, expanded, onToggle, onClick, onKey,
}: {
  row: LongListRow;
  expanded: boolean;
  onToggle(): void;
  onClick(e: MouseEvent<HTMLTableRowElement>, pick: Pick): void;
  onKey(e: KeyboardEvent<HTMLTableRowElement>, pick: Pick): void;
}) {
  const p = r.pick;
  const detailId = `ll-detail-${p.id}`;
  return (
    <tr
      className="ll-row"
      data-char={p.character_slug ?? 'none'}
      tabIndex={0}
      title="Open the pick"
      onClick={(e) => onClick(e, p)}
      onKeyDown={(e) => onKey(e, p)}
    >
      <td className="ll-pic">
        <PickThumb pick={p} size="small" />
      </td>
      <th scope="row" className="ll-clip">
        <div className="ll-clip-in">
          <button
            type="button"
            className="ll-chev"
            aria-expanded={expanded}
            aria-controls={expanded ? detailId : undefined}
            aria-label={expanded ? 'Hide the reasoning and checks' : 'Show the reasoning and checks'}
            onClick={onToggle}
          >
            <ChevronRight size={15} aria-hidden="true" />
          </button>
          {/^https:/.test(p.url) ? (
            <a className="ll-title" href={p.url} target="_blank" rel="noopener noreferrer" title={`${r.title} (opens the original in a new tab)`}>
              {r.title}
              <ExternalLink size={11} aria-hidden="true" />
            </a>
          ) : (
            <span className="ll-title">{r.title}</span>
          )}
        </div>
      </th>
      <td className="ll-character">{p.character_slug ? <Livery slug={p.character_slug} /> : <span className="faint">—</span>}</td>
      <td className="ll-tier">
        <span className={`tier-badge tier-${r.tier}`}>{TIER_LABELS[r.tier]}</span>
      </td>
      <td className="ll-n">{r.rec ?? '—'}</td>
      <td className="ll-n">{compactCount(r.views)}</td>
      <td className="ll-n">{r.age?.label ?? '—'}</td>
      <td className="ll-n">{perDay(r.velocity)}</td>
      <td className="ll-n">{outlierCell(r.outlier)}</td>
      <td className="ll-n">{r.sat ?? '—'}</td>
      <td className="ll-n">{scoreCell(r.fit)}</td>
      <td className="ll-n">{scoreCell(r.feas)}</td>
      <td className="ll-mode">{r.mode ? MODE_LABEL[r.mode] : '—'}</td>
      <td className="ll-n" title={r.creditsEstimated ? 'Worked out here: the analyst gave no estimate' : 'The analyst’s estimate'}>
        {r.creditsEstimated ? '≈' : ''}
        {r.credits}
      </td>
      <td className="ll-n ll-score">
        <b>{r.score == null ? '—' : Math.round(r.score)}</b>
      </td>
    </tr>
  );
}

function Detail({ row: r, onOpen }: { row: LongListRow; onOpen(pick: Pick): void }) {
  const p = r.pick;
  const tags = [p.source_status, p.audio_risk, p.season ? `season: ${p.season}` : null].filter((t): t is string => Boolean(t));
  const candidates = (p.source_candidates ?? []).filter((c) => c && typeof c === 'object');
  return (
    <tr className="ll-detail" id={`ll-detail-${p.id}`}>
      <td colSpan={COLUMN_COUNT}>
        <div className="ll-detail-in">
          {p.why ? (
            <p className="pick-why">
              <b>Why:</b> {p.why}
            </p>
          ) : (
            <p className="small muted" style={{ margin: 0 }}>No reasoning recorded for this pick.</p>
          )}
          {(p.checks ?? []).length > 0 && (
            <div className="ll-checks">
              <span className="label">Checks</span>
              <ul className="how-list plain">
                {(p.checks ?? []).map((c) => (
                  <li key={c}>{c}</li>
                ))}
              </ul>
            </div>
          )}
          {tags.length > 0 && (
            <ul className="chips ll-tags" aria-label="Clip and audio">
              {tags.map((t) => (
                <li key={t} className="tag how-filter">
                  {t}
                </li>
              ))}
            </ul>
          )}
          {candidates.length > 0 && (
            <div className="ll-checks">
              <span className="label">Clean-clip candidates</span>
              <ul className="how-list plain">
                {candidates.map((c, i) => (
                  <li key={String(c.id ?? c.url ?? i)} className="small">
                    {[c.id ?? c.url, typeof c.views === 'number' ? `${compactCount(c.views)} views` : null, c.why].filter(Boolean).join(' · ')}
                  </li>
                ))}
              </ul>
            </div>
          )}
          {p.original_url && /^https:/.test(p.original_url) && p.original_url !== p.url && (
            <a className="small" href={p.original_url} target="_blank" rel="noopener noreferrer">
              The famous original <ExternalLink size={11} aria-hidden="true" />
            </a>
          )}
          <div>
            <button type="button" className="btn line" onClick={() => onOpen(p)}>
              Open the pick
            </button>
          </div>
        </div>
      </td>
    </tr>
  );
}
