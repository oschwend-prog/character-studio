// Owner actions shared by more than one screen.
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
