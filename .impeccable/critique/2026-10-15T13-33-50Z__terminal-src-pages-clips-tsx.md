---
target: Clips page
total_score: 21
max_score: 40
na_heuristics: 
p0_count: 1
p1_count: 2
target_identity: "file:/Users/olivierschwend/Claude/Projects/character-studio/.claude/worktrees/nervous-grothendieck-210153/terminal/src/pages/Clips.tsx"
target_fingerprint: "sha256:198794f1597a64f2afd7431ed93bbbe7e9e1079606bd63e11365fdf2c6e60262"
target_path: /Users/olivierschwend/Claude/Projects/character-studio/.claude/worktrees/nervous-grothendieck-210153/terminal/src/pages/Clips.tsx
timestamp: 2026-10-15T13-33-50Z
slug: terminal-src-pages-clips-tsx
---
# Critique: Clips page (terminal/src/pages/Clips.tsx), 2026-10-15
Method: dual-agent (A: design review · B: detector + browser overlay)

| # | Heuristic | Score | Key issue |
|---|---|---|---|
| 1 | System status | 2 | Higgsfield out of credits is never said; only the studio cap shows |
| 2 | Real world | 3 | "Make this" only adds to a list |
| 3 | Control | 3 | Undo, two-step confirm, Clear |
| 4 | Consistency | 2 | Make this / Make it / Make selected / Yes, make N; amber Top pick badges |
| 5 | Error prevention | 3 | Nothing warns a make is certain to fail (no credits) |
| 6 | Recognition | 2 | Rules taught in paragraphs, not at the point of use |
| 7 | Efficiency | 1 | ~10,800 px phone page, no jump to a character, no folding |
| 8 | Minimalist | 1 | 2,236 px of strangers' hits before his clips; 35 line buttons |
| 9 | Error recovery | 2 | Raw "Higgsfield refused the job" text; amber Try again that fails again |
| 10 | Help | 2 | Plenty of help, wrong place |
| Total | | 21/40 | Acceptable, serious IA problems |

Priority issues
- P0 IA: Hot right now (y 681-2917 on a phone) comes before the owner's clips (first at ~3,500, Ready at ~7,570).
- P1 Out of credits: drop.credits_refused_at / reason never read by the terminal; ReadyCard does not render drop.reason; no page-level line; Try again stays amber.
- P1 Lit plate: permanent amber Choose videos outranks Needs you; amber Top pick badges carry rank, not need.
- P2 Explainer text: 5-line intro + 6-line score/retention hint before content.
- P2 Make this is a list tick; the Make bar idles at the very bottom.
- P3 Seg buttons 38 px (< 44); "Try again · about 135" wraps to 3 lines; Recommend card half-width with blank half.

Detector: CLI 0 on TSX (rules live in CSS). Overlay 11: tab labels 9.5 px x5 + date 10.5 px (shell), side-stripe on Drop box and Hot right now (real), nested-cards on the Drop box seg (false positive), tight leading on card titles (debatable), ai-color-palette on placeholder thumbs (false positive).
