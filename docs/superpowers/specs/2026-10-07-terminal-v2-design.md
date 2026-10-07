# Terminal v2: built around the owner's clip folder, with a style per character

Owner, 2026-10-07: "For now the terminal should be structured around the clips I download and put into a folder. We then match
our characters with them, generate the video and post. I want a clearer overview: daily dashboard, long list of clips,
suggestions who to drop in and why, videos under way, all live videos per character, all super easy to use. Keep the viral
scanning, but aside, not as the focus." Then: "Adjust the text and text pill per character, something flashy for the DJ type;
the video can change slightly with the hook too."

Owner decisions on 2026-10-07: the clips folder is an **iCloud Drive folder**; the per-character styles are the four shown in
chat (Franz posh card, Reginald silver tray, Lenny gold call, DJ rave flyer), each with its hook edit.

Three parts, each buildable and testable on its own, in this order: A (small, unblocks the owner's workflow), B, C.

## Unchanged rules (CLAUDE.md stays binding)
- All state through `bin/studio`; schema `studio` only; no secrets in files; media never in git (the folder lives outside the repo).
- Nothing is generated without the owner's Make it; the price shows before it. Posting stays approval-only until an account has
  6 approved posts.
- Masters: 1080x1920, 30 fps, 6-16 s, -14 LUFS; they end on the dance (no close-up); the two ODD EYES dots stay in every caption
  pill and the two-dot bug top right; no audio is added that the clip did not carry; the AI label on every post.
- The terminal keeps its current look (cards, colours, type, components). Only the organisation changes.

## A. The clips folder (iCloud Drive)
- Folder: `iCloud Drive/ODD EYES clips/` (on the Mac `~/Library/Mobile Documents/com~apple~CloudDocs/ODD EYES clips/`), created
  by the install step. The owner saves clips there from the iPhone (Files, Safari downloads, Photos "Save to Files") or the Mac.
- `bin/studio drop sync-folder [--folder PATH]`: for each video file in the folder (`.mp4 .mov .m4v`, any case): skip an iCloud
  placeholder that is not downloaded yet (ask iCloud to fetch it with `brctl download`, take it on a later run); skip a file
  still being written (size changed in the last 30 s); skip a file whose content hash is in the ledger (already added: it was
  copied again); otherwise upload it exactly as `drop add --file` does today (no character: the studio recommends one), record
  the hash in the ledger, and move the file into `Added/` inside the folder so the owner sees what was taken. A failed upload
  leaves the file where it is and is retried on the next run. Prints JSON like every command (`added`, `skipped`, `failed`).
- Ledger: `~/.local/state/odd-eyes/clips-ledger.json` (hash -> pick id, time); not in the repo.
- Runs every 5 minutes through a user LaunchAgent (`com.oddeyes.clip-sync`), installed by `bin/install-clip-sync` (idempotent,
  `--uninstall` too), log in `~/Library/Logs/odd-eyes-clip-sync.log`. Only while the Mac is awake: the daily run also calls
  `drop sync-folder` first, as a safety net. The terminal's Add clips button (files, links) keeps working from anywhere.
- Risk to verify first: macOS may refuse a background process access to iCloud Drive (privacy). If it does, the install step
  says exactly which permission to grant (System Settings, Privacy and Security), and the fallback is the daily run's sync.
- Links stay in the terminal (paste a link); no link files in the folder.

## B. The terminal: five sections in the order of the work
Tab bar: **Today · Clips · Videos · Characters · More**. Today is the home. Old addresses keep working
(`#/works` -> Clips, `#/queue` -> Videos, `#/library` and `#/channels` -> Characters, `#/picks` and `#/budget` -> More).

1. **Today (daily dashboard).**
   - Four counts, each a link to its filtered list: clips needing a character, ready to make (with the total credits), making
     now, videos to approve.
   - Tonight's posts per live character: slot, the video (or "Approve a video" / "Nothing yet"), Approve in one tap.
   - Last posts per character: views, likes, shares of the latest posts (from the metrics snapshots); before the first post,
     one quiet line saying they appear here.
   - Credits left this month (one line) and warnings only when something is wrong (failed post, failed drop, low credits).
2. **Clips (the long list: the folder's clips).** One row per drop, newest first: thumbnail with play, length, a status
   chip, the ★ suggestion with its reason, the character menu (Recommend by default; the owner's choice is never overridden),
   the price and Make it. Filters: All, Needs a character, Ready, Making, Done, Blocked or failed (with Try again).
   Status chip = one plain word from the drop and clip states: Adding, Checking, Pick a character, Ready, Making, Done
   (it moved to Videos), Blocked, Failed. The Add clips box sits at the top. This replaces "In the works".
3. **Videos (everything after Make it).** Three groups: Making (with started time), To approve (player, hook, caption, first
   comment, slot, credit switch, Approve or Reject: today's Queue), Scheduled (when and where it goes out). Posted videos
   move to their character.
4. **Characters.** A row of character cards (avatar, status, handle, next slot); each opens his page: the profile (today's
   artist page) and all his videos grouped Live (with views), Scheduled, In the making. An "All characters" view lists every
   video (today's Library).
5. **More.** Viral scan (today's Picks page as it is; it keeps running), Budget, Health and settings.

Data: the existing views (`v_tracker`, `v_queue`, the channels and clips data); no new tables. If a count needs a field the
views lack, the plan names the smallest additive change. Demo mode (`?demo=1`) covers every section.

## C. A style per character (caption pill + hook edit)
Each character gets a style kit, written in `characters/<slug>/refs.json` under `style` and read by `bin/studio master build`
(local and in the cloud drop job). A character without one keeps today's dark pill. Fonts are OFL files in `assets/fonts/` with
their licence. The pill keeps its band (top at y 1300) and the two dots; size, wrap (at most 2 lines) and the 42-character hook
rule stay.

| Character | Pill | How it comes in | Hook edit on the video | Tone |
| --- | --- | --- | --- | --- |
| Franz | cream `#F4EBDD`, navy `#1F2A44` italic serif, round corners | slow fade and rise (0.4 s) | slow push-in 1.00 -> 1.06 over the first 1.5 s | warm |
| Reginald | black `#0E0F12` card, thin off-white rule, off-white spaced small caps serif, square corners | appears, no motion | the butler's pause: the first frame held 0.4 s in silence, then the clip plays in sync | cool, a little desaturated |
| Lenny | gold `#E8B931`, black bold condensed capitals | slams in (scale 1.15 -> 1.00 in 0.15 s) | quick punch-in 1.15 -> 1.00 in the first 0.5 s | golden |
| DJ (parked; kit ready for when he goes live) | neon yellow `#E6FF00`, tilted -4 deg, orange `#FF7A00` block behind, black heavy italic capitals | word by word on the beat | a white flash and two zoom pulses on the drop (the beat found by `source analyze`) | punchy, saturated |

- Tones are subtle colour adjustments (ffmpeg colour filters), never a look that hides the character.
- The hook edit stays within the first second or the drop moment; the master length rule still holds (Reginald's pause adds
  0.4 s and counts toward the 16 s maximum).
- The Borat-type gets his kit once he has a name.
- Every kit is checked on real frames of an existing master (Reginald's Wednesday, Franz H2, Lenny H1) before it is used:
  frame sheets shown to the owner; re-mastering an existing clip is free (no Higgsfield credits).

## Testing
- A: unit tests for the scan rules (placeholder, still writing, ledger hit, move to Added, failed upload left in place) on a temp
  folder with a fake uploader; one real run on the Mac with a test clip.
- B: the terminal's tests for the status mapping, the counts and the old-address redirects; `npm run build`; the in-app browser
  at phone width and desktop in demo mode, then live.
- C: tests for the kit parsing and the filter chains; `qa tech` on re-mastered clips (length, loudness, 1080x1920); frame sheets.

## Out of scope
New characters, the subscription idea, TikTok accounts, any change to how picks are scanned or scored.
