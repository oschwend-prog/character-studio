# Product

<!-- impeccable:product-schema 1 -->

> Written 2026-10-05 during Task 15 (the terminal) by an unattended build agent with no question
> channel to the owner. Every fact below comes from the repository (spec, plan, CLAUDE.md, launch
> docs, character bibles) or the owner's directives quoted in the task brief. Lines marked
> *(inferred)* are the agent's reading and should be confirmed by the owner.

## Platform

web

## Stack

Repository plan: the studio itself is a Python CLI (`bin/studio`) over Supabase Postgres (schema
`studio`) + Storage. The owner's surface is `terminal/`, a Vite + React + TypeScript single-page app
on Vercel, installable as a PWA, talking to Supabase directly with the anon key, magic-link auth and
row-level security (owner email only).

## Users

One user: the owner, Olivier, running ODD EYES as a side venture next to a full-time investment
business. He checks in from his phone, one-handed, in short sessions (morning, evening around the
19:00 / 19:30 London posting slots) *(inferred from "mobile-first, one-handed" in the brief)*.
His job in the terminal: approve what the machine made, see what is going out today, see whether it
is working, and stop spending if needed. Directive (2026-10-04): "as autonomous as possible, very
easy to use for me, state of the art".

## Product Purpose

ODD EYES is an autonomous AI-character studio: it scans trends, scores "Viral Picks", produces 1080p
clips of its characters (Biscuit, a baby-blue dachshund; Reginald "the Quiff", a deadpan butler),
QA's them, and posts them to TikTok and Instagram Reels. The terminal is the single control surface:
approval queue, channel results, every clip ever made, credit spend against the monthly cap, and the
kill switch. Success = the owner spends a few taps a day and the machine keeps posting within its
rules.

## Positioning

Not a social-media scheduler and not an analytics suite: a control room for a machine that already
runs on its own. Every screen answers "does it need me?" first.

## Operating Context

- Daily run (Claude scheduled task) scans, plans, produces and queues clips; an hourly health check
  and a 15-minute publisher run on GitHub Actions. The terminal shows their state; it never runs them.
- Posting slots are London time: Biscuit 19:00, Reginald 19:30; weeks 1-2 Tue/Wed/Thu, then Mon-Fri.
- Budget: Higgsfield credits, default cap 6,000 per London month; a kill switch stops new spend.
- Viral Picks: six sub-scores (virality, reach, freshness, fit, feasibility, saturation, 0-10) and a
  total (0-100); standing rule auto-approves total >= 80 with feasibility >= 7, skips < 65.
- Autopilot per account (`mode = auto`): clips that pass QA skip the approval queue. Locked off until
  the account has 6 approved posts.
- KPIs: outlier_x (views_7d / median of the account's last 15), a hit = outlier_x >= 3. Bars are
  pre-registered and binding.

## Capabilities and Constraints

- Owner-only: RLS on every table keyed to the owner's email; the service key never reaches a browser.
- Never posts more than 2x per account per day; never without the AI label; never past the cap.
- No scraping or downloading from TikTok/Instagram: a Viral Pick is a link to the original, opened in
  a new tab, never embedded or fetched.
- Media is private in Supabase Storage (`clips` bucket); the browser plays masters through
  short-lived signed URLs.
- Follower counts per account are not stored yet (only per-post follows) *(open decision)*.

## Brand Commitments

- Name: ODD EYES. Mark: two dots, ice-blue `#8FD3FF` and amber `#FFB040` (the characters' mismatched
  eyes: right eye ice-blue, left eye amber).
- Biscuit: baby blue `#A7C7E7`. Reginald: racing green `#0B3D2E` + gold `#C9A227`.
- The owner's other terminals are dark and dense (spec 4.6: "Dark, dense style consistent with the
  owner's other terminals").

## Evidence on Hand

- Batch-1 Viral Picks with real URLs, views, outlier x and scores: `docs/launch/viral-picks-2026-10-04.md`.
- Character bibles: `characters/biscuit/bible.md`, `characters/reginald/bible.md`; avatars in `assets/avatars/`.
- No live clips, posts or metrics yet (accounts not created as of 2026-10-05). Any clip, post or
  metric shown in demo mode is synthetic and labelled as such.

## Product Principles

1. "Does it need me?" first: every screen leads with what is waiting on the owner, then what is running.
2. Two taps to any action; one tap for the common one (Approve all).
3. Autonomy is earned: autopilot unlocks per account only after 6 approved posts.
4. Show the rule with the number: every automatic decision carries its reason.
5. Spend is always visible and always stoppable.

## Accessibility & Inclusion

WCAG AA contrast, full keyboard operation, screen-reader labels on every control (task brief).
