// The clip card's Keep (terminal v3 spec section 10, retention; owner 2026-10-07): a clip nobody made is deleted after a while (a
// hit's after 30 days, the owner's own after 60: studio source purge --stale), unless he marks it Keep (set_drop_keep, migration
// 0016). Shown only where retention can delete (lib/hits keepable): a drop not made yet.
import { keepHint, keepable } from '../lib/hits';
import { dropTitle } from '../lib/drop';
import { useStudio } from '../lib/store';
import type { TrackerRow } from '../lib/types';

export function KeepToggle({ row, idPrefix = 'keep' }: { row: TrackerRow; idPrefix?: string }) {
  const { backend, run, busy } = useStudio();
  if (!keepable(row)) return null;
  const kept = row.drop_card?.keep === true;
  const key = `keep-${row.pick_id}`;
  const working = busy.has(key);
  const id = `${idPrefix}-${row.pick_id}`;
  const toggle = () =>
    void run(key, () => backend.setDropKeep(row.pick_id, !kept), kept ? `Not kept: ${keepHint(false).toLowerCase()}` : keepHint(true));
  return (
    <div className="keep">
      {/* a label around the switch: a tap on the word works too (a button is labelable) */}
      <label className="keep-hit">
        <button
          type="button" role="switch" className="switch small" aria-checked={kept} aria-label={`Keep ${dropTitle(row)}`}
          aria-describedby={`${id}-d`} disabled={working} aria-busy={working} onClick={toggle}
        />
        <span className="small keep-label" aria-hidden="true">Keep</span>
      </label>
      <span className="hint" id={`${id}-d`}>{keepHint(kept)}</span>
    </div>
  );
}
