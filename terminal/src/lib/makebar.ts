// Terminal v3, the tick-and-make bar (spec 5.2 and 6; Review Focus 5): nothing ticked by default; "Make 3 selected · 291 credits";
// a confirm step on the page with the total, the month's budget left and the cap; only then Make it for each clip, one by one,
// and each clip's own result. The state machine and the confirm's numbers live here, pure and tested; MakeBar.tsx only draws them.
import { formatCredits } from './format';
import { selectionTotal, type MakeResult } from './ranking';
import type { Budget, TrackerRow } from './types';

export type MakeBarState =
  /** Ticking: the bar shows the count and the price. */
  | { step: 'pick' }
  /** The owner tapped the bar: the confirm shows the total for exactly these clips (frozen when it opened). */
  | { step: 'confirm'; ids: string[] }
  /** He confirmed: Make it is being asked for these clips, one by one. */
  | { step: 'sending'; ids: string[] }
  /** Each clip's own result, until he closes it. */
  | { step: 'done'; results: MakeResult[] };

export type MakeBarEvent =
  | { type: 'open'; ids: ReadonlyArray<string> }
  | { type: 'cancel' }
  | { type: 'send' }
  | { type: 'finished'; results: MakeResult[] }
  | { type: 'close' };

export const MAKE_BAR_START: MakeBarState = { step: 'pick' };

/**
 * The bar's steps. `open` (with at least one clip, each once) only from ticking or from the last results; `send` only from the
 * confirm, keeping its clips; `finished` only while sending; `cancel` and `close` go back to ticking. Anything else changes nothing,
 * so a stray tap can never skip the confirm.
 */
export function makeBarReducer(s: MakeBarState, e: MakeBarEvent): MakeBarState {
  switch (e.type) {
    case 'open': {
      const ids = [...new Set(e.ids)];
      return (s.step === 'pick' || s.step === 'done') && ids.length ? { step: 'confirm', ids } : s;
    }
    case 'cancel':
      return s.step === 'confirm' ? MAKE_BAR_START : s;
    case 'send':
      return s.step === 'confirm' ? { step: 'sending', ids: s.ids } : s;
    case 'finished':
      return s.step === 'sending' ? { step: 'done', results: e.results } : s;
    case 'close':
      return s.step === 'done' ? MAKE_BAR_START : s;
  }
}

/**
 * The clips to ask Make it for when the bar moves from `prev` to `next`: the confirm's clips exactly when the confirm was open and
 * the owner confirmed (confirm → sending); none for any other step. The screen calls makeMany only with a non-empty answer.
 */
export function idsToSend(prev: MakeBarState, next: MakeBarState): string[] {
  return prev.step === 'confirm' && next.step === 'sending' ? [...next.ids] : [];
}

/** What the confirm says, and whether it lets him go on. */
export interface ConfirmFacts {
  /** The ticked clips that still have a price (checked), each once. */
  count: number;
  credits: number;
  /** What is left of this month's cap now; null when the budget could not be read. */
  left: number | null;
  cap: number | null;
  /** What is left after these clips; null without a budget. */
  leftAfter: number | null;
  /** One plain line when he may not go on (the kill switch, past the cap, nothing priced); null when he may. */
  blocked: string | null;
}

/**
 * The confirm's numbers for the frozen ids: the total at the prices the rows show (selectionTotal: each clip's own Adjust), what is
 * left of the month's cap and after. He may not go on with the kill switch on, past what is left of the cap, or with nothing priced.
 */
export function confirmFacts(rows: ReadonlyArray<Pick<TrackerRow, 'pick_id' | 'drop_card'>>, ids: ReadonlyArray<string>, budget: Pick<Budget, 'cap' | 'committed' | 'kill_switch'> | null): ConfirmFacts {
  const { count, credits } = selectionTotal(rows, ids);
  const left = budget ? Math.max(0, budget.cap - budget.committed) : null;
  const leftAfter = left == null ? null : left - credits;
  let blocked: string | null = null;
  if (count === 0) blocked = 'None of these clips has a price yet: they are still being checked.';
  else if (budget?.kill_switch) blocked = 'The kill switch is on: nothing is made until you resume it (More, Budget).';
  else if (left != null && credits > left) blocked = `That is more than the ${formatCredits(left)} left this month. Untick some clips.`;
  return { count, credits, left, cap: budget?.cap ?? null, leftAfter, blocked };
}

const intGB = new Intl.NumberFormat('en-GB', { maximumFractionDigits: 0 });

/** Credits in words, as the bar says them: "291 credits", "1 credit". */
export function creditsWords(n: number): string {
  const r = Math.round(n);
  return `${intGB.format(r)} ${r === 1 ? 'credit' : 'credits'}`;
}

/** The bar's button: "Make 3 selected · 291 credits"; "Make selected" while nothing is ticked. */
export function makeBarLabel(total: { count: number; credits: number }): string {
  return total.count > 0 ? `Make ${total.count} selected · ${creditsWords(total.credits)}` : 'Make selected';
}

/** The results' heading: "3 clips sent to be made", "2 clips sent to be made, 1 refused", "Nothing was sent: 2 refused". */
export function resultsHeading(results: ReadonlyArray<Pick<MakeResult, 'ok'>>): string {
  const sent = results.filter((r) => r.ok).length;
  const refused = results.length - sent;
  if (sent === 0) return refused ? `Nothing was sent: ${refused} refused` : 'Nothing was sent';
  const head = sent === 1 ? '1 clip sent to be made' : `${sent} clips sent to be made`;
  return refused ? `${head}, ${refused} refused` : head;
}

/** The ids of `selected` that can still be made from these rows (the Ready clips), in the order given. A clip that was made,
 * removed or went back to checking since he ticked it drops out of the selection on its own. */
export function liveSelection(selected: Iterable<string>, makeable: ReadonlySet<string>): string[] {
  return [...new Set(selected)].filter((id) => makeable.has(id));
}
