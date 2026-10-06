// Types of scripts/bible.mjs (the artist card parser), for the tests that import it. The card's shape is `Artist` in
// src/lib/artist.ts.
import type { Artist, ArtistItem } from '../src/lib/artist';

export function section(markdown: string, heading: string): string;
export function listItems(text: string): ArtistItem[];
export function firstParagraph(text: string): string | null;
export function blocks(text: string): { label: string; lead: string; items: ArtistItem[] }[];
export function table(text: string): Record<string, string>[];
export function boldQuote(text: string): string | null;
export function edition(voice: string): string | null;
export function voiceOf(text: string): { preset: string | null; voice_id: string | null; sample_file: string | null };
export function cdnPrefix(refs: Record<string, unknown>, bible: string): string | null;
export function plannedHandle(social: string): string | null;
export function parseArtist(
  refs: Record<string, unknown> & { slug: string },
  bible?: string,
  social?: string,
  files?: { spec?: boolean; turnaround?: boolean; avatar?: boolean },
): Artist;
