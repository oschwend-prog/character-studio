// Higgsfield out of credits on the Clips page (owner 2026-10-15): the studio's stamp on a Ready drop and the owner's failed Make it
// make one page line; a make that went through after them clears it. Pure functions over v_tracker rows; no browser.
import { describe, expect, it } from 'vitest';
import { NO_CREDITS_LINE, creditsOut, creditsRefusedAt } from './credits';
import { dropLine } from './drop';
import type { DropCard, DropState, TrackerRow } from './types';

const NOW = Date.parse('2026-10-15T13:00:00Z');
const ago = (m: number) => new Date(NOW - m * 60_000).toISOString();
const card = (state: DropState, over: Partial<DropCard> = {}): DropCard => ({ state, kind: 'link', at: ago(5), ...over });
const row = (drop: DropCard): TrackerRow => ({ pick_id: `p-${Math.random()}`, drop_card: drop }) as unknown as TrackerRow;

const STUDIO = 'Higgsfield said not enough credits at 14:00; the studio asks again after 02:00';
const OWNER = 'Higgsfield refused the job: Higgsfield refused the submit: HTTP 403: {"detail": "Insufficient credits"}';

describe('creditsRefusedAt', () => {
  it('reads the studio stamp on a Ready drop and the owner’s failed Make it', () => {
    expect(creditsRefusedAt(card('ready', { credits_refused_at: ago(60), reason: STUDIO }))).toBe(ago(60));
    expect(creditsRefusedAt(card('failed', { reason: OWNER, at: ago(30) }))).toBe(ago(30));
    expect(creditsRefusedAt(card('failed', { reason: 'Higgsfield refused the job: not_enough_credits', at: ago(30) }))).toBe(ago(30));
  });
  it('ignores other failures and an old stamp on a drop that was made since', () => {
    expect(creditsRefusedAt(card('failed', { reason: 'the quality check failed twice' }))).toBeNull();
    expect(creditsRefusedAt(card('making', { credits_refused_at: ago(60) }))).toBeNull();
  });
});

describe('creditsOut', () => {
  it('says it once, with the time of the newest refusal', () => {
    const out = creditsOut([row(card('ready', { credits_refused_at: ago(120) })), row(card('failed', { reason: OWNER, at: ago(30) }))], NOW);
    expect(out?.at).toBe(ago(30));
    expect(out?.line).toMatch(/^Higgsfield is out of credits \(since \d\d:\d\d\)\. Checks stay free/);
  });
  it('is quiet when nothing was refused, after a day, or once a make went through after the refusal', () => {
    expect(creditsOut([row(card('ready'))], NOW)).toBeNull();
    expect(creditsOut([row(card('ready', { credits_refused_at: ago(25 * 60) }))], NOW)).toBeNull();
    const refused = row(card('ready', { credits_refused_at: ago(60) }));
    expect(creditsOut([refused, row(card('making', { make: { submitted_at: ago(10) } }))], NOW)).toBeNull();
    expect(creditsOut([refused, row(card('making', { make: { submitted_at: ago(90) } }))], NOW)).not.toBeNull();
  });
});

describe('dropLine', () => {
  it('puts a failed card’s credits refusal in plain words', () => {
    expect(dropLine(card('failed', { reason: OWNER }), NOW)).toBe(NO_CREDITS_LINE);
    expect(dropLine(card('ready', { credits_refused_at: ago(60), reason: STUDIO }), NOW)).toBe(STUDIO);
  });
});
