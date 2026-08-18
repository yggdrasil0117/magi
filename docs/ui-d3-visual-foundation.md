# UI-D3: visual foundation and component contract

Status: accepted; all six UI-D3 decisions confirmed

## Direction

UI-D3 translates the accepted UI-D2 hierarchy into an EVA/MAGI-like operational
interface without changing workflow semantics. It uses amber information on warm
black, severe cut geometry, compact technical labels, equal three-perspective
modules, and state-triggered alarm treatment. Meaningful Chinese remains the
primary instruction layer.

Official-material slots remain optional and are governed by
`docs/ui-asset-governance.md`. The default build uses an original three-cell MAGI
mark and contains no copied logo, screenshot, character, slogan, or series font.

## Color tokens

| Token | Value | Purpose |
|---|---:|---|
| `void` | `#070806` | page and terminal background |
| `surface-01` | `#10120E` | navigation and persistent shell |
| `surface-02` | `#171912` | ordinary panels |
| `surface-03` | `#202318` | selected and raised regions |
| `line-subtle` | `#363326` | separators and quiet frames |
| `line-signal` | `#756138` | structural signal frames |
| `text-primary` | `#F1E9D7` | body and headings |
| `text-secondary` | `#AAA497` | metadata and secondary copy |
| `operational` | `#F2A72B` | navigation, active data, main frame |
| `operational-hi` | `#FFD36F` | compact highlights, never body blocks |
| `nominal` | `#A8D46F` | confirmed, ready, online |
| `caution` | `#F2A72B` | unresolved, waiting, conditional states |
| `alarm` | `#FF5145` | denied, failed, destructive, unsafe only |
| `focus` | `#FFF0A6` | keyboard focus ring |

On `void`, primary, secondary, operational, nominal, alarm, and focus text colors
must meet WCAG AA for normal text. `operational-hi` is restricted to short labels.
Perspective identity is primarily code and geometry; color is supplemental:

- MELCHIOR `M-01`: continuous upper rule;
- BALTHASAR `B-02`: split upper rule;
- CASPER `C-03`: stepped upper rule.

This avoids giving the three equal votes misleading success/warning/error colors.

## Typography

No network font or copyrighted series typeface is required.

| Role | Stack | Size / line height |
|---|---|---|
| Display state | `Bahnschrift Condensed`, `Arial Narrow`, Chinese sans | fluid 32–64 / 0.92 |
| Section heading | same condensed stack | 20–28 / 1.1 |
| Chinese body | `Microsoft YaHei UI`, `PingFang SC`, sans-serif | 15–16 / 1.65 |
| Technical data | `Cascadia Mono`, `Consolas`, monospace | 11–13 / 1.4 |
| Action label | Chinese sans plus technical micro-label | 15 / 1.2 |

IDs, hashes, timestamps, vote counts, state names, and protocol values use monospace.
Long reasoning never uses condensed or monospace text.

## Spatial and frame tokens

- base spacing unit: 4 px; named steps: 4, 8, 12, 16, 24, 32, 48, 64;
- content frame: 1 px signal line plus 4–8 px state edge;
- cut sizes: 8 px compact, 16 px panel, 24 px state/display;
- minimum control height: 44 px; minimum pointer target: 44 by 44 px;
- report reading measure: 68 Chinese characters or 76 Latin characters;
- wide rails: navigation 256 px, diagnostics 304 px;
- wide content gap: 16 px; narrow content gap: 12 px.

Cut corners are created with CSS masks or pseudo-elements. DOM reading order remains
rectangular and logical. Diagonal stripes are limited to destructive confirmation
and hard protocol failure, never used as a general background texture.

## Component contract

### `CommandHeader`

Contains the original or approved licensed mark, product name, protocol, connection,
and sync state. A missing licensed mark swaps to the original mark without layout
shift. Connection state includes visible text; a green dot alone is insufficient.

### `DecisionLocator`

Contains title, decision ID, version, risk, classification, and owner projection.
It stays above section navigation and never becomes decorative telemetry.

### `StateBanner`

Variants: `draft`, `waiting`, `ready`, `processing`, `completed`, `unresolved`,
`degraded`, `failed`, `denied`, `cancelled`. Anatomy is state code, plain-language
title, explanation, and optional real summary value. Only `failed` and `denied`
receive full alarm styling; `degraded` uses an alarm edge with neutral body.

### `FramePanel`

An indexed region with technical label, Chinese title, and body. It may be selected,
focused, cautionary, or dissenting. A panel cannot be clickable unless it exposes
button/link semantics and keyboard behavior.

### `PerspectiveCell`

Equal modules for M-01, B-02, and C-03. States are `sealed`, `queued`, `running`,
`received`, `preliminary`, `reviewing`, `final`, and `unavailable`. Before permitted
disclosure, there is no hidden vote value in DOM attributes or accessible labels.

### `ActionGate`

Contains command class, consequence copy, one primary action, and optional secondary
navigation. Cancel/destructive actions live in a separated alarm subsection. A
mutation always opens a second confirmation surface; loading disables repeat issue
but does not replace the consequence copy.

### `DissentPanel`

Appears in the first report reading sequence, not behind an accordion. It names the
perspective, retained/revised status, disagreement, and reconsideration condition.
Its visual weight is below the result but equal to the majority explanation.

### `OptionalAssetSlot`

Accepts only a configured `asset_id`. It exposes a fallback, aspect ratio, crop
policy, attribution location, and decorative/informative flag. Informative imagery
requires meaningful alternative text; decorative imagery has empty alternative text.

## Iconography and marks

The original mark is three offset cells around a central decision point. Original
icons use straight strokes, square terminals, and 2 px line weight at 24 px. Do not
approximate NERV or series marks when no licensed asset exists. Familiar generic
symbols may be used for search, export, link, warning, and disclosure, always with
visible labels for critical actions.

## Motion

- fast acknowledgement: 120 ms;
- panel/state transition: 220 ms;
- first-load stagger: maximum 360 ms total;
- easing: `cubic-bezier(.2,.8,.2,1)`;
- no continuous blinking, scan loop, jitter, CRT flicker, or ambient alarms.

Real state changes may use one scan/acquire transition. `prefers-reduced-motion`
removes translation, stagger, and scan effects. Loading uses text plus a quiet
indeterminate rule rather than invented progress.

## Density modes

`command` is the default and exposes the full frame/index grammar. `reading` keeps
the palette and state identity but removes background grid, suppresses optional art,
reduces micro-labels, and gives report prose a quieter surface. User preference is
client-owned and cannot alter data, state, or report order.

## Responsive behavior

- 1200 px and above: persistent navigation, workspace, diagnostic rails;
- 768–1199 px: navigation drawer, one content column, diagnostic strip after state;
- 360–767 px: single flow, horizontal section navigation, all art hidden first;
- 200% browser zoom at 1280 px: no two-dimensional page scrolling;
- terminal: 120+ columns split layout, 80–119 compact layout, below 80 stacked.

Report content, dissent, consequences, and recovery actions are never removed at a
breakpoint. Tables become labelled cards instead of horizontal overflow.

## Focus and accessibility

- one 3 px `focus` ring with 3 px offset, never removed by frame clipping;
- skip link targets workspace content;
- heading levels reflect page structure, independent of display size;
- status uses text and structure in addition to color;
- error summaries link to invalid fields; focus moves only after user action;
- live regions announce authoritative stage changes only, not timers or decoration;
- contrast, keyboard, no-color terminal, reduced motion, and 200% zoom are release
  acceptance requirements.

## Terminal visual contract

ANSI is optional. Default mapping uses 256-color approximations 208 (operational),
203 (alarm), 149 (nominal), 254 (primary), and 245 (secondary) on black. The no-color
mode preserves `[WAIT]`, `[READY]`, `[ALERT]`, `[DONE]`, `M-01/B-02/C-03`, border
weight, and section indices. Unicode frame characters fall back to ASCII `+|-` when
terminal capability is unknown.

The TUI does not render raster official assets. An approved identity may appear as
text only when its permission covers that representation. State-changing shortcuts
always enter a confirmation prompt and are disabled inside text inputs.

## Representative prototype

`apps/web/prototypes/ui-d3.html` demonstrates confirmation, completed report, and
degraded recovery states; command/reading density; responsive collapse; original
fallback mark; licensed slots; keyboard focus; and reduced-motion behavior. It uses
synthetic data and does not call the API or ship through the production server.

## Confirmed UI-D3 decisions

1. Accept the amber/black operational palette with red reserved for true alarms.
2. Accept system condensed/monospace stacks without copied series fonts.
3. Accept the frame, state banner, perspective cell, action gate, dissent, and asset
   slot component contracts.
4. Accept `command` and `reading` density modes.
5. Accept the original three-cell mark as the unlicensed fallback.
6. Accept the responsive, motion, terminal, focus, and accessibility rules.

These six decisions are frozen. UI-D4 production work must use these tokens and
component semantics unless a separately reviewed visual revision supersedes them.
