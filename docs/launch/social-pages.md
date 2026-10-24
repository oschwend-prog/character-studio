# Social pages kit (paste-ready) — ODD EYES studio

Owner creates the accounts (Claude cannot create accounts). Everything else below is ready to paste.

## Account rules (both characters, both platforms)
1. **Creator** account type — not Business (Business accounts get a reduced music library).
2. Same handle on TikTok and Instagram if available; check the 3 options in order.
3. Turn on **AI-generated content** labelling (TikTok: "AI-generated content" setting per post / Instagram: "AI info" label). Bios say "AI character".
4. 2-factor authentication on; use a password manager.
5. Profile picture: the square avatar below (crops to a circle).
6. Connect each account to **Postiz** after creation.

## Biscuit 🌭💙
- **Display name:** Biscuit 🌭💙
- **Handles (try in order):** `biscuit.moves` · `smoothbiscuit` · `biscuitthesausage`
- **TikTok bio (≤80):** smoothest sausage online 🌭 mismatched eyes, matched beats · AI character
- **Instagram bio (≤150):**
  The smoothest sausage on the internet 🌭💙
  Mismatched eyes. Perfect timing.
  New moves every week · AI-generated character 🤖
- **Profile picture:** `assets/avatars/biscuit.png` (job `57870be0-bd09-4bca-9193-853f46e26d1f`, ODD EYES)
- **Pinned (first 3 posts):** 1) intro — "they said sausages can't dance" 2) "my eyes don't match. my moves do." 3) best performer after week 2

## Reginald 🎩
- **Display name:** Reginald 🎩
- **Handles (try in order):** `reginald.thebutler` · `thedancingbutler` · `butlerreginald`
- **TikTok bio (≤80):** Head butler. The quiff never moves. 🎩 · AI character
- **Instagram bio (≤150):**
  Head butler. The quiff never moves. 🎩
  The household is unaware.
  AI-generated character 🤖
- **Profile picture:** Quiff avatar job `ecaf6a89-77ff-4d5a-bf92-24beb2b20c93` → `assets/avatars/reginald.png`
- **Pinned:** 1) intro — "The quiff never moves." 2) "Not a single drop spilled." 3) best performer after week 2

## Crossover
Biscuit is the house dog at Reginald's stately home. Crossover clips (both characters in one video) post to both accounts and cross-tag — the cheapest follower transfer between the two.

## Collab posts (owner 2026-10-24)
Each character's first Reel of the week goes out with one of the others as Instagram collaborator (`studio/collab.py`, switch `reach.collabs` in `config/scan.json`, from Mon 26 Oct). The partners rotate weekly: week A Franz with Reginald, Reginald with Lenny, Lenny with Franz; week B the reverse. So each profile gets 2 collab Reels a week.
- **Your step:** the partner's Instagram account receives a collab invite (a notification) when the Reel posts. Accept it in that character's Instagram app. Until then the Reel shows only on the author's profile; nothing breaks if one is missed.
- **Change or remove** a partner before the post: `bin/studio clip set <clip> --collab <handle>` or `--no-collab`.
- A collab Reel is never a Trial Reel (Instagram's rule), and TikTok copies go out solo.
- **If Instagram refuses a collab Reel** (`studio health` lists the post as failed; collabs were first sent live from 26 Oct): `bin/studio clip set <clip> --no-collab`, then `bin/studio publish resolve <post> --retry` posts it solo.
