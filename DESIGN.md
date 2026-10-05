---
name: ODD EYES terminal
description: The owner's departures board for an autonomous AI-character studio. Dark, dense, one lit plate.
colors:
  board: "#0e0f11"
  panel: "#15171a"
  panel-2: "#1b1e22"
  tile: "#202328"
  tile-top: "#24282d"
  rule: "#2b2f35"
  rule-strong: "#3b4047"
  ink: "#ede8de"
  ink-2: "#b4afa5"
  ink-3: "#8d8980"
  ice: "#8fd3ff"
  ice-track: "#233a48"
  amber: "#ffb040"
  amber-ink: "#1c1203"
  amber-track: "#3d2c12"
  red: "#ff6b5b"
  red-ink: "#210604"
  red-track: "#43201c"
  biscuit: "#a7c7e7"
  biscuit-ink: "#0e2033"
  reginald: "#0b3d2e"
  reginald-gold: "#c9a227"
  series-biscuit: "#5c97d4"
  series-reginald: "#b08c1c"
typography:
  flap-display:
    fontFamily: "'Archivo Variable', system-ui, sans-serif"
    fontSize: "50px"
    fontWeight: 560
    lineHeight: 1
    letterSpacing: "normal"
  flap:
    fontFamily: "'Archivo Variable', system-ui, sans-serif"
    fontSize: "15px"
    fontWeight: 620
    lineHeight: 1
    letterSpacing: "normal"
  title:
    fontFamily: "'Archivo Variable', system-ui, sans-serif"
    fontSize: "24px"
    fontWeight: 640
    lineHeight: 1.1
    letterSpacing: "-0.01em"
  section:
    fontFamily: "'Archivo Variable', system-ui, sans-serif"
    fontSize: "13px"
    fontWeight: 700
    lineHeight: 1.2
    letterSpacing: "0.09em"
  body:
    fontFamily: "'Archivo Variable', system-ui, sans-serif"
    fontSize: "15px"
    fontWeight: 400
    lineHeight: 1.4
    letterSpacing: "normal"
  label:
    fontFamily: "'Archivo Variable', system-ui, sans-serif"
    fontSize: "11px"
    fontWeight: 640
    lineHeight: 1.2
    letterSpacing: "0.08em"
rounded:
  cell: "2px"
  sm: "4px"
  pill: "18px"
spacing:
  hair: "2px"
  xs: "6px"
  sm: "10px"
  md: "16px"
  lg: "22px"
components:
  button-primary:
    backgroundColor: "{colors.amber}"
    textColor: "{colors.amber-ink}"
    rounded: "{rounded.sm}"
    padding: "0 16px"
    height: "44px"
  button-line:
    backgroundColor: "transparent"
    textColor: "{colors.ink}"
    rounded: "{rounded.sm}"
    padding: "0 16px"
    height: "44px"
  button-danger:
    backgroundColor: "transparent"
    textColor: "{colors.red}"
    rounded: "{rounded.sm}"
    height: "44px"
  flap-cell:
    backgroundColor: "{colors.tile}"
    textColor: "{colors.ink}"
    typography: "{typography.flap}"
    rounded: "{rounded.cell}"
    width: "13px"
    height: "22px"
  livery-biscuit:
    backgroundColor: "{colors.biscuit}"
    textColor: "{colors.biscuit-ink}"
    rounded: "{rounded.cell}"
    height: "22px"
  livery-reginald:
    backgroundColor: "{colors.reginald}"
    textColor: "{colors.reginald-gold}"
    rounded: "{rounded.cell}"
    height: "22px"
  needs-plate:
    backgroundColor: "{colors.amber}"
    textColor: "{colors.amber-ink}"
    rounded: "{rounded.sm}"
    padding: "12px"
  input:
    backgroundColor: "{colors.board}"
    textColor: "{colors.ink}"
    rounded: "{rounded.sm}"
    height: "44px"
---

# Design System: ODD EYES terminal

## Overview

**Creative North Star: "The Departures Board"**

The terminal is a split-flap departures board for a studio that posts on its own. Every channel's 19:00 / 19:30 London slot is a departure with a clip, a livery and a status. The owner reads it top-down in a few seconds on a phone, one-handed, and the one thing that needs him is the only lit plate on the screen.

It refuses the KPI-tile dashboard: no big-number cards with sparklines, no glow, no glass panels for their own sake. Density is a virtue; legibility comes from a fixed grid of tiles, weight and case, not from size inflation.

**Key Characteristics:**
- Matte charcoal board, off-white characters on split-flap tiles with a hinge line.
- One family (Archivo, width axis): condensed for tiles and labels, normal width for reading.
- Character liveries as airline plates: Biscuit baby blue, Reginald racing green with gold.
- Ice-blue means live or posted; amber means it needs you or can be pressed; vermilion means failed or stopped.
- Motion is stepped, like the machine it borrows from.

## Colors

Restrained: a neutral board plus two brand signals taken from the ODD EYES mark (the characters' mismatched eyes).

### Primary
- **Amber** (#ffb040): the action and "needs you" colour. Primary buttons, the needs plate, waiting statuses on the board, badges for waiting work. Text on it is Amber Ink (#1c1203).

### Secondary
- **Ice** (#8fd3ff): live and done. Posted / posting statuses, the autopilot switch when on, outlier hits, the spend meter fill under 80 %, focus rings.

### Tertiary
- **Vermilion** (#ff6b5b): failed posts, critical alerts, reject, the kill switch, spend over the cap.

### Neutral
- **Board** (#0e0f11) page ground; **Panel** (#15171a) and **Panel 2** (#1b1e22) for grouped surfaces; **Tile** (#202328) / **Tile Top** (#24282d) for flap cells; **Rule** (#2b2f35) hairlines.
- **Ink** (#ede8de) primary text, **Ink 2** (#b4afa5) secondary, **Ink 3** (#8d8980) muted (4.5:1 or better on every surface it sits on).
- Character colours are identity only: liveries use the bible colours (#a7c7e7, #0b3d2e + #c9a227); charts use the validated series steps (#5c97d4, #b08c1c), checked with the dataviz validator on the board.

### Named Rules
**The One Lit Plate Rule.** At most one amber filled plate or primary per screen region that competes for the thumb. A second action next to it is a line button.

**The Meaning Rule.** Ice, amber and vermilion carry state. They are never decoration, and a coloured mark always has a word or number beside it.

## Typography

**Display / tiles:** Archivo Variable at 62–80 % width, weight 560–640, uppercase on tiles.
**Body:** Archivo Variable at 100 % width, weight 400, 15 px / 1.4.
**Labels:** Archivo 82 % width, 11 px, 0.08 em tracking, uppercase.

### Hierarchy
- **Flap display** (50 px on phones, 64 px desktop, tiles 40×62 / 52×78): the next departure time, once per screen.
- **Title** (24 px, 640): page names.
- **Section** (13 px, 700, 0.09 em, uppercase): section heads with a hairline under them.
- **Body** (15 px) and **small** (13 px) for content; numbers in columns use tabular figures.
- **Label** (11 px uppercase): table column heads and form labels only.

### Named Rules
**The Rank by Weight Rule.** Hierarchy comes from weight, width and case inside a tight scale (11 / 13 / 15 / 24 and one display size), not from many sizes.

## Layout

Mobile-first, one column, 16 px gutters, safe-area insets on top bar and tab bar. A fixed bottom tab bar (six tabs, 64 px) on phones becomes a 92 px left rail from 960 px. Today splits into board (left) and picks / spend / autopilot / health (right) on desktop. Section rhythm is 22 px between sections and 10 px inside them. The board is a grid: time · livery · gate · status, with the hook and clip code on a second line on phones and in a fifth column from 720 px.

## Elevation & Depth

Flat by default: surfaces separate by value and hairlines. Shadows appear only on things that float over scrolling content (the needs plate, toasts), soft and offset downward. The sticky top bar and the queue dock blur what scrolls under them for legibility, nothing else.

## Shapes

Small radii: 2 px on tiles and liveries, 4 px on buttons, inputs and panels, a pill only on filter chips and the autopilot switch. No circles except the two-dot mark and the switch knob.

## Components

### Buttons
44 px tall minimum, 4 px radius, uppercase condensed label with 0.06 em tracking. Primary is amber on amber ink; line is transparent with a 1 px inset rule; danger is vermilion text with a vermilion-track rule, solid vermilion only for the final confirm. Busy buttons show a small ring spinner and `aria-busy`.

### Chips
36 px pill toggles on tile, `aria-pressed`, used for filters and quick reasons (skip, reject).

### Cards / Containers
Panels, not floating cards: Panel background, 1 px Rule border, 4 px radius, hairline-divided rows inside. Never nested.

### Inputs / Fields
44 px, Board background, Rule Strong border, ice border + ring on focus, amber caret, vermilion border when invalid.

### Navigation
Bottom tab bar (rail on desktop) with icon + condensed uppercase label; the current tab gets Ink colour and a 2 px Ink bar; amber count badge for waiting work, quiet tile badge for informational counts.

### Split-flap (signature)
Each character sits on its own tile with a hinge line. When a value changes (Realtime), the changed cells step through the drum and land; reduced motion swaps instantly. Screen readers get the plain text once. Used for times, statuses, gate codes, counts and scores; never for long text.

### Needs plate (signature)
The only amber filled surface on Today: count, what waits, Review and Approve all. Sticky above the tab bar while there is work, gone when there is none.

## Do's and Don'ts

### Do:
- **Do** lead every screen with what needs the owner, then what is running.
- **Do** keep every action within two taps and the common one within one.
- **Do** show the rule with the number (autopilot 4 of 6, "held by the rule: needs multi body").
- **Do** label demo or synthetic data where a visitor could mistake it for the real thing.

### Don't:
- **Don't** add KPI hero tiles, sparklines or gradient text.
- **Don't** put a label above a heading (eyebrow); put the code or icon inline instead.
- **Don't** use ice, amber or vermilion for decoration.
- **Don't** ease or fade state changes on the board; flaps step.
