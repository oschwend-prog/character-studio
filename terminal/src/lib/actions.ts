// Owner actions shared by more than one screen.
import { retryAdjust } from './drop';
import { makeMany, makeSummary, type MakeResult } from './ranking';
import { approveAll, SLOT_RULE } from './rules';
import { useStudio } from './store';

/** "Approve all": one RPC per clip, never stopping at a refusal; one toast with the count. */
export function useApproveAll() {
  const { backend, run } = useStudio();
  return (ids: string[]) =>
    run(
      'approve-all',
      async () => {
        const r = await approveAll(backend, ids);
        if (r.refused.length) throw new Error(r.summary);
      },
      `${ids.length} approved. ${SLOT_RULE}.`,
    );
}

/**
 * "Make N selected" (terminal v3, spec 5.2), called only after the screen's confirm with the total: Make it for each ticked clip,
 * one by one (makeMany), each with the Adjust its price was shown for; one toast with the outcome, then a reload. Resolves with
 * each clip's own result, so the screen can show which ones were refused and why (Review Focus 5).
 */
export function useMakeMany() {
  const { backend, data, run } = useStudio();
  return async (pickIds: string[]): Promise<MakeResult[]> => {
    const cards = new Map((data?.tracker ?? []).map((r) => [r.pick_id, r.drop_card]));
    let results: MakeResult[] = [];
    const sent = new Set(pickIds).size;
    await run(
      'make-many',
      async () => {
        results = await makeMany(backend, pickIds, (id) => {
          const d = cards.get(id);
          return d ? retryAdjust(d) : null;
        });
        if (results.some((r) => !r.ok)) throw new Error(makeSummary(results));
      },
      sent === 1 ? '1 clip sent to be made' : `${sent} clips sent to be made`,
    );
    return results;
  };
}
