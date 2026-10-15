// Higgsfield out of credits on the Clips page (owner 2026-10-15, Clips redesign). Higgsfield answers a submit from an account short
// of credits with HTTP 403 "Insufficient credits" and charges nothing (studio/higgsfield_api.py). A make the studio asked for goes
// back to Ready stamped `credits_refused_at` (studio/drop.py _refused_for_credits); the owner's own Make it ends Failed with
// Higgsfield's words in its reason. The page says it once at the top and on the Make bar; a failed card says it in plain words and
// its Try again is not lit.
import { londonTime } from './format';
import type { DropCard, TrackerRow } from './types';

/** How long a refusal stays news: the studio asks again after 12 h (CREDITS_REFUSED_HOLD_H), a day covers one more ask. */
export const CREDITS_NEWS_H = 24;
const NO_CREDITS = /HTTP 403|insufficient credits|not[ _]enough[ _]credits/i;

/** What a failed card says instead of Higgsfield's raw refusal. */
export const NO_CREDITS_LINE = 'Higgsfield had no credits: nothing was spent. Top up, then Try again.';

/** When Higgsfield refused this drop for credits (the studio's stamp on a Ready drop, or the owner's failed Make it), else null. */
export function creditsRefusedAt(d: DropCard): string | null {
  if (d.state === 'ready' && d.credits_refused_at) return d.credits_refused_at;
  if (d.state === 'failed' && d.reason && NO_CREDITS.test(d.reason)) return d.at ?? null;
  return null;
}

/**
 * The page's one line when Higgsfield is out of credits: the newest refusal of the last day, unless a make went through after it
 * (Higgsfield took a submit since: the owner topped up). Null when there is nothing to say.
 */
export function creditsOut(rows: ReadonlyArray<TrackerRow>, now: number): { at: string; line: string } | null {
  let refused: number | null = null;
  let madeSince = 0;
  for (const r of rows) {
    const d = r.drop_card;
    if (!d) continue;
    const at = creditsRefusedAt(d);
    const t = at ? Date.parse(at) : NaN;
    if (!Number.isNaN(t)) refused = refused == null ? t : Math.max(refused, t);
    const sent = d.make?.submitted_at ? Date.parse(d.make.submitted_at) : NaN;
    if ((d.state === 'making' || d.state === 'made') && !Number.isNaN(sent)) madeSince = Math.max(madeSince, sent);
  }
  if (refused == null || now - refused > CREDITS_NEWS_H * 3_600_000 || madeSince > refused) return null;
  return {
    at: new Date(refused).toISOString(),
    line: `Higgsfield is out of credits (since ${londonTime(refused)}). Checks stay free; Make it works again once you top up.`,
  };
}
