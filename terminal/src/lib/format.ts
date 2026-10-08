// Display formatting. Every time is shown in Europe/London, like the studio itself.

const LONDON = 'Europe/London';
const intGB = new Intl.NumberFormat('en-GB', { maximumFractionDigits: 0 });
const compactGB = new Intl.NumberFormat('en-US', { notation: 'compact', maximumFractionDigits: 1 });

export type Tone = 'hit' | 'good' | 'neutral' | 'weak' | 'none';

const isNum = (n: number | null | undefined): n is number => typeof n === 'number' && Number.isFinite(n);

/** `1234` -> `"1,234 cr"` (Higgsfield credits). `null` -> an em dash. */
export function formatCredits(n: number | null | undefined): string {
  return isNum(n) ? `${intGB.format(Math.round(n))} cr` : '—';
}

/**
 * The outlier_x badge, on the pre-registered bars: >= 3 is a hit, >= 1.5 good (the format keep
 * line), <= 0.7 weak (the kill line), anything between neutral. No result yet -> a dash.
 */
export function outlierBadge(x: number | null | undefined): { label: string; tone: Tone } {
  if (!isNum(x)) return { label: '—', tone: 'none' };
  const label = x >= 100 ? `${intGB.format(Math.round(x))}×` : `${x.toFixed(1)}×`;
  if (x >= 3) return { label, tone: 'hit' };
  if (x >= 1.5) return { label, tone: 'good' };
  if (x <= 0.7) return { label, tone: 'weak' };
  return { label, tone: 'neutral' };
}

/** `43_400_000` -> `"43.4M"`. */
export function formatViews(n: number | null | undefined): string {
  return isNum(n) ? compactGB.format(n) : '—';
}

/** Time left until `target` (epoch ms or ISO) from `now`: "3h 12m", "12m", "now", "2d 3h", or "gone". */
export function formatCountdown(target: number | string, now: number = Date.now()): string {
  const t = typeof target === 'string' ? Date.parse(target) : target;
  const ms = t - now;
  if (ms < 0) return 'gone';
  const mins = Math.floor(ms / 60_000);
  if (mins < 1) return 'now';
  const days = Math.floor(mins / 1440);
  const hours = Math.floor((mins % 1440) / 60);
  const rest = mins % 60;
  if (days > 0) return `${days}d ${hours}h`;
  if (hours > 0) return `${hours}h ${rest}m`;
  return `${rest}m`;
}

/** How long ago a moment was: "just now", "30m ago", "2h ago", "1d 2h ago", "3d ago". No moment -> an em dash. */
export function formatAge(from: string | number | null | undefined, now: number = Date.now()): string {
  if (from == null) return '—';
  const ms = now - (typeof from === 'string' ? Date.parse(from) : from);
  const mins = Math.floor(ms / 60_000);
  if (!(mins >= 1)) return 'just now';
  const days = Math.floor(mins / 1440);
  const hours = Math.floor((mins % 1440) / 60);
  if (days > 0) return hours > 0 ? `${days}d ${hours}h ago` : `${days}d ago`;
  if (hours > 0) return `${hours}h ago`;
  return `${mins}m ago`;
}

const timeFmt = new Intl.DateTimeFormat('en-GB', { timeZone: LONDON, hour: '2-digit', minute: '2-digit', hourCycle: 'h23' });
const dayKeyFmt = new Intl.DateTimeFormat('en-CA', { timeZone: LONDON, year: 'numeric', month: '2-digit', day: '2-digit' });
const dateFmt = new Intl.DateTimeFormat('en-GB', { timeZone: LONDON, weekday: 'short', day: 'numeric', month: 'short' });
const stampFmt = new Intl.DateTimeFormat('en-GB', {
  timeZone: LONDON, day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit', hourCycle: 'h23',
});

const asDate = (v: string | number | Date) => (v instanceof Date ? v : new Date(v));

/** "19:00": the London wall-clock time of a moment. */
export const londonTime = (v: string | number | Date) => timeFmt.format(asDate(v));
/** "2026-10-07": the London calendar day of a moment. */
export const londonDayKey = (v: string | number | Date) => dayKeyFmt.format(asDate(v));
/** The calendar day `n` days after the day key `key` (YYYY-MM-DD), counted on the calendar: a clock change never skips or repeats
 * a day (24 h steps would, near midnight). */
export function addDays(key: string, n: number): string {
  const [y, m, d] = key.split('-').map(Number);
  return new Date(Date.UTC(y, m - 1, d + n)).toISOString().slice(0, 10);
}
/** "Tue 6 Oct". */
export const londonDate = (v: string | number | Date) => dateFmt.format(asDate(v)).replace(',', '');
/** "6 Oct, 19:00". */
export const londonStamp = (v: string | number | Date) => stampFmt.format(asDate(v));

const PREFIX: Record<string, string> = { franz: 'FRZ', reginald: 'RGN', lenny: 'LNY', biscuit: 'BSC' };

/**
 * A character's three-letter code (the livery plate, the clip code): the roster's own, else the first three letters or digits of
 * the slug ("borat-type" -> "BOR"), "???" for a slug with none.
 */
export function characterCode(slug: string | null | undefined): string {
  if (!slug) return '???';
  return PREFIX[slug] ?? (slug.replace(/[^a-z0-9]/gi, '').slice(0, 3).toUpperCase() || '???');
}

/** A short flight-number style code for a clip: "FRZ 3F9A". */
export function clipCode(id: string, characterSlug: string): string {
  return `${characterCode(characterSlug)} ${id.replace(/-/g, '').slice(0, 4).toUpperCase()}`;
}

/** "TikTok" / "Instagram" / "YouTube". */
export function platformName(p: string | null | undefined): string {
  if (p === 'tiktok') return 'TikTok';
  if (p === 'instagram') return 'Instagram';
  if (p === 'youtube') return 'YouTube';
  return p ?? '—';
}

const partsFmt = new Intl.DateTimeFormat('en-GB', {
  timeZone: LONDON, year: 'numeric', month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit',
  second: '2-digit', hourCycle: 'h23',
});

function londonParts(ms: number): Record<string, number> {
  const out: Record<string, number> = {};
  for (const p of partsFmt.formatToParts(new Date(ms))) if (p.type !== 'literal') out[p.type] = Number(p.value);
  return out;
}

/** London's offset from UTC at a moment, in ms (+1 h in summer). */
function londonOffset(ms: number): number {
  const p = londonParts(ms);
  return Date.UTC(p.year, p.month - 1, p.day, p.hour, p.minute, p.second) - Math.floor(ms / 1000) * 1000;
}

/** A `datetime-local` value ("2026-10-06T19:00") read as London wall time -> ISO instant. */
export function londonWallToIso(wall: string): string {
  const m = /^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2})$/.exec(wall.trim());
  if (!m) throw new Error(`expected YYYY-MM-DDTHH:MM, got ${JSON.stringify(wall)}`);
  const asUtc = Date.UTC(+m[1], +m[2] - 1, +m[3], +m[4], +m[5]);
  let ms = asUtc - londonOffset(asUtc);
  ms = asUtc - londonOffset(ms); // second pass lands on the right side of a clock change
  return new Date(ms).toISOString();
}

/** An instant -> the London `datetime-local` value ("2026-10-06T19:00"). */
export function isoToLondonWall(iso: string | number): string {
  const p = londonParts(typeof iso === 'number' ? iso : Date.parse(iso));
  const two = (n: number) => String(n).padStart(2, '0');
  return `${p.year}-${two(p.month)}-${two(p.day)}T${two(p.hour)}:${two(p.minute)}`;
}

/** "Wed": the London weekday of a moment. */
export const londonWeekday = (v: string | number | Date) =>
  new Intl.DateTimeFormat('en-GB', { timeZone: LONDON, weekday: 'short' }).format(asDate(v));
