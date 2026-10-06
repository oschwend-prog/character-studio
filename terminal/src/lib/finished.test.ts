// "Finished clips" on In the works (owner 2026-10-06): every made clip with its player; approving stays in the Queue.
import { describe, expect, it } from 'vitest';
import { FINISHED_LABEL, FINISHED_STATES, finishedClips } from './finished';
import type { ClipState, LibraryClip } from './types';

const clip = (id: string, state: ClipState, created: string, posted: string | null = null) =>
  ({ id, state, created_at: created, posted_at: posted }) as Pick<LibraryClip, 'id' | 'state' | 'created_at' | 'posted_at'>;

describe('the finished clips', () => {
  it('are the clips waiting for the owner, approved, scheduled or posted: his OK first, then booked, then posted, newest first', () => {
    const list = [
      clip('p-old', 'posted', '2026-10-01T10:00:00Z', '2026-10-02T18:00:00Z'), clip('gen', 'generating', '2026-10-06T10:00:00Z'),
      clip('ok', 'awaiting_approval', '2026-10-05T10:00:00Z'), clip('sch', 'scheduled', '2026-10-04T10:00:00Z'),
      clip('p-new', 'posted', '2026-10-01T09:00:00Z', '2026-10-05T18:00:00Z'), clip('rej', 'rejected', '2026-10-06T09:00:00Z'),
      clip('ok-new', 'awaiting_approval', '2026-10-06T08:00:00Z'), clip('appr', 'approved', '2026-10-06T07:00:00Z'), clip('drop', 'dropped', '2026-10-06T06:00:00Z'),
    ];
    expect(finishedClips(list).map((c) => c.id)).toEqual(['ok-new', 'ok', 'appr', 'sch', 'p-new', 'p-old']);
    expect(FINISHED_STATES.map((s) => FINISHED_LABEL[s])).toEqual(['Your OK', 'Approved', 'Scheduled', 'Posted']);
  });

  it('come from the demo with a clip waiting for the owner and posted ones', async () => {
    const { DemoBackend } = await import('../demo/backend');
    const snap = await new DemoBackend(() => Date.parse('2026-10-06T12:00:00Z')).load();
    const done = finishedClips(snap.library);
    expect(done[0].state).toBe('awaiting_approval');
    expect(done.some((c) => c.state === 'posted') && done.every((c) => (FINISHED_STATES as ReadonlyArray<string>).includes(c.state))).toBe(true);
  });
});
