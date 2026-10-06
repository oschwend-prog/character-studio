// The exact text a post goes out with, as studio.captions.compose_content builds it: the caption, the AI disclosure line (unless
// that exact line is already in it), a blank line, the hashtags. At most 5 hashtags, none of the dead ones, 2,200 characters at
// most counted in UTF-16 units (a JS string's own length). parity-cases.json `captions` holds the cases both sides must agree on.
// Also the Copy button's logic: the clipboard when the browser allows it, else "select and copy".

export const AI_DISCLOSURE = 'AI-generated character 🤖';
export const CAPTION_LIMIT = 2200;
export const HASHTAG_LIMIT = 5;
export const BANNED_HASHTAGS: ReadonlyArray<string> = ['explore', 'foryou', 'foryoupage', 'fyp', 'viral'];

/** Length in UTF-16 code units (an emoji is 2), what a platform's limit may count: exactly a JS string's length. */
export const captionLength = (text: string) => text.length;

/** Hashtags with their `#`, trimmed, empty ones dropped, de-duplicated (case-insensitive), in order. */
export function cleanTags(hashtags: ReadonlyArray<string>): string[] {
  const seen = new Set<string>();
  const out: string[] = [];
  for (const raw of hashtags) {
    const tag = raw.trim().replace(/^#+/, '').trim();
    if (tag && !seen.has(tag.toLowerCase())) {
      seen.add(tag.toLowerCase());
      out.push(`#${tag}`);
    }
  }
  return out;
}

const pyStrip = (s: string) => s.replace(/^\s+|\s+$/g, '');

/** The post text, or an Error with the same sentence the studio raises (a banned tag, a sixth tag, over 2,200 characters). */
export function composeContent(caption: string, hashtags: ReadonlyArray<string>): string {
  let text = pyStrip(caption);
  if (!text.includes(AI_DISCLOSURE)) text = text ? `${text}\n\n${AI_DISCLOSURE}` : AI_DISCLOSURE;
  const tags = cleanTags(hashtags);
  for (const tag of tags) {
    if (BANNED_HASHTAGS.includes(tag.slice(1).toLowerCase())) {
      throw new Error(
        `hashtag ${tag} is refused: ${BANNED_HASHTAGS.map((t) => `#${t}`).join(', ')} reach nobody (use the moment, the niche, the format and #oddeyes)`,
      );
    }
  }
  if (tags.length > HASHTAG_LIMIT) {
    throw new Error(`${tags.length} hashtags, over the limit of ${HASHTAG_LIMIT} (Instagram's cap): keep the moment, the niche, the format and #oddeyes`);
  }
  const content = tags.length ? `${text}\n\n${tags.join(' ')}` : text;
  const n = captionLength(content);
  if (n > CAPTION_LIMIT) {
    throw new Error(
      `the post text is ${n} characters with the AI disclosure and hashtags, over the ${CAPTION_LIMIT} limit: shorten the caption by ${n - CAPTION_LIMIT} or more`,
    );
  }
  return content;
}

/** For the screen: the composed text, or the reason it would be refused (never throws). */
export function postText(caption: string | null | undefined, hashtags: ReadonlyArray<string> | null | undefined): { text: string | null; error: string | null } {
  try {
    return { text: composeContent(caption ?? '', hashtags ?? []), error: null };
  } catch (e) {
    return { text: null, error: e instanceof Error ? e.message : String(e) };
  }
}

/** What the Copy button does: `copied` when the clipboard took it, `select` when the page must select it for the owner to copy. */
export async function copyText(text: string, clipboard: Pick<Clipboard, 'writeText'> | null | undefined): Promise<'copied' | 'select'> {
  if (!clipboard || typeof clipboard.writeText !== 'function') return 'select';
  try {
    await clipboard.writeText(text);
    return 'copied';
  } catch {
    return 'select'; // not allowed here (an insecure page, an iframe, a denied permission)
  }
}

// ---- the credit line (owner 2026-10-06: crediting the original creator is optional, a switch per post) ----------------

/** A credit line of the caption formula: "🎵 song – artist · dance: @creator", "trend: @x", "dance: @x" or "original: x". */
const CREDIT_START = /^(?:🎵\s|trend:\s|dance:\s|original:\s)/i;

export interface RemovedCredit {
  line: string;
  index: number;
}

/** The caption's credit line, or null when it has none. */
export function creditLine(caption: string): string | null {
  return caption.split('\n').find((l) => CREDIT_START.test(l.trim())) ?? null;
}

/** The caption without its credit line, and the line with its position (to put it back); `removed` is null when there was none. */
export function withoutCredit(caption: string): { text: string; removed: RemovedCredit | null } {
  const lines = caption.split('\n');
  const index = lines.findIndex((l) => CREDIT_START.test(l.trim()));
  if (index < 0) return { text: caption, removed: null };
  const [line] = lines.splice(index, 1);
  return { text: lines.join('\n'), removed: { line, index } };
}

/** The caption with the credit line back where it was (clamped to the end); unchanged when it already has one. */
export function withCredit(caption: string, removed: RemovedCredit): string {
  if (creditLine(caption)) return caption;
  const lines = caption.split('\n');
  lines.splice(Math.min(removed.index, lines.length), 0, removed.line);
  return lines.join('\n');
}
