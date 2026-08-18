# UI-D2: Web and terminal wireframes

Status: accepted; all six UI-D2 decisions confirmed

## Decisions carried from UI-D1

The decision inbox, versioned workspace, five workspace sections, separate
confirmation/run gates, and preliminary-only first-round disclosure are frozen for
this proposal. EVA/MAGI visual direction is required. Official-material placements
are optional slots governed by `docs/ui-asset-governance.md`.

## Shared screen anatomy

Every workspace screen uses the same reading order:

1. command header: product identity, connection, authoritative state;
2. decision locator: title, ID, version, risk, classification;
3. state module: what is happening, what the user must do, and why;
4. primary content: the selected workspace section;
5. three-perspective diagnostic: equal MELCHIOR/BALTHASAR/CASPER status;
6. action gate: only commands listed by `available_actions`;
7. protocol footer: last synchronized time, API/protocol version, and audit link.

Optional licensed imagery is visually subordinate to this order. Removing every
official slot must not move an action, erase a label, or change the meaning.

## Web wide layout

~~~text
┌─ OPTIONAL LICENSED MARK ─ MAGI SYSTEM / STATE / CONNECTION ─────────┐
│ INBOX / NEW       │ DECISION LOCATOR + STATE MODULE       │ DIAGNOSTIC │
│                   │                                      │ M / B / C  │
│ active decisions  │ OVERVIEW EVIDENCE PERSPECTIVES       │ protocol   │
│ required action   │ REPORT AUDIT                         │ metadata   │
│                   │                                      │ optional   │
│ navigation        │ PRIMARY CONTENT                      │ asset slot │
│                   │                                      │            │
├─────────────────┴─ ACTION GATE / PLAIN-LANGUAGE CONSEQUENCE ──┴───────────┤
└─ ID / VERSION / LAST SYNC / PROTOCOL / AUDIT REFERENCE ──────────────┘
~~~

At 1200 px and above, the inbox rail is 240–280 px, the diagnostic rail is
280–320 px, and the center owns all remaining width. Report prose is capped at a
comfortable line length inside the center rather than stretched edge to edge.

## Web responsive behavior

| Width | Structure | Action behavior |
|---|---|---|
| 1200 px+ | three columns | action gate remains below primary content |
| 768–1199 px | navigation drawer + content; diagnostics below state | actions remain in document flow |
| 360–767 px | one column; section tabs become horizontal scroller | primary action appears after consequence copy; no overlay on report |

On narrow screens, the order is header, locator, state, section navigation, content,
diagnostics, action gate, footer. Optional reference frames and character art are
hidden first. No critical content becomes a hover-only tooltip.

## Core Web screens

### 01 Decision inbox

Rows prioritize required action, title, state, version, risk, and update time.
Search and state filters are secondary. An unavailable list API produces an honest
"not available in this build" panel rather than sample decisions.

### 02 New decision

Question and options come first, followed by constraints, risk/classification, and
evidence. The final button says "Submit for normalization", not "Run MAGI". Client
validation points to fields but never claims evidence is verified.

### 03 Confirmation

The center uses raw/normalized comparison on wide screens and sequential labelled
blocks on narrow screens. Unknowns and evidence boundary appear before actions.
Primary action is "Confirm and freeze"; edit and cancel are visually separate.

### 04 Run gate

The screen states that the case is frozen but no perspective has started. It lists
the three model calls, disclosure rules, and expected cost/latency only when the
server supplies real estimates. "Start assessment" is the only primary action.

### 05 First ballot

Three sealed modules show queued/running/received without vote values, rationale,
or fake percentages. The user may leave and reconnect; no mutation is offered.

### 06 Cross-review

Released first-round views may appear in three equal modules under the repeated
label "First round — preliminary, not final". Review ballots remain hidden. The
timeline names the bounded review stage without simulating thought traces.

### 07 Final report

The first viewport shows result status, selected option when decisive, vote count,
majority rationale, and a prominent dissent entry. Risks, conditions, missing
information, next step, evidence references, and review audit follow. Export does
not outrank reading the dissent.

### 08 Evidence and audit

Evidence uses labelled cards below tablet width and a table only when columns fit.
Audit events show actor class, command, outcome, timestamp, and references. Hidden
model reasoning, credentials, and restricted evidence never receive placeholder
rows because their existence may itself be sensitive.

### 09 Non-decisive and recovery

Insufficient information, conditional rejection, degraded, failed, denied,
offline, timeout, malformed response, empty inbox, and report-not-ready each have
distinct titles and recovery actions. Only failed/denied/unsafe states use the red
alert region. A non-decisive result never displays a winning option.

## Terminal layouts

### Wide terminal: 120 columns or more

~~~text
┏ MAGI // EVIDENCE_READY ━ decision: dec-017 / v03 ━ LINK:ONLINE ━┓
┃ DECISIONS (24)       ┃ 04 RUN GATE                              ┃
┃ > dec-017  READY     ┃ Case is frozen. Assessment has not run.  ┃
┃   dec-012  COMPLETE  ┃                                           ┃
┃                      ┃ [M] MELCHIOR  SEALED  [B] BALTHASAR SEALED┃
┃ SECTIONS             ┃ [C] CASPER     SEALED                     ┃
┃ 1 Overview           ┃                                           ┃
┃ 2 Evidence           ┃ Consequence: starts three model calls.    ┃
┃ 3 Perspectives       ┃                                           ┃
┃ 4 Report             ┃ [R] START ASSESSMENT   [Esc] BACK         ┃
┃ 5 Audit              ┃                                           ┃
┗━ F1 HELP ━ SYNC 14:32:08 ━ PROTOCOL 1.0 ━ NO PARTIAL BALLOTS ━┛
~~~

### Medium terminal: 80–119 columns

Navigation becomes a single top line; diagnostics move below the state module.
The primary content retains at least 48 columns. Pressing `g` opens a navigation
palette rather than relying on a permanently visible left pane.

### Narrow terminal: below 80 columns

Screens stack: header, locator, state, content, diagnostics, actions. `[` and `]`
move between the five sections. Lines wrap at word boundaries, tables become
label/value blocks, and all state labels remain present in no-color mode.

State-changing keys always open a consequence prompt that requires a second,
explicit confirmation. Single-key shortcuts are ignored while focus is in text
input. `q` leaves the client and never cancels a decision.

## Web/TUI semantic mapping

| Meaning | Web | Terminal |
|---|---|---|
| Workspace sections | labelled tab row | keys 1–5 / navigation palette |
| State module | dominant center panel | first content block |
| Three perspectives | diagnostic rail or stacked cards | equal labelled status blocks |
| Primary command | action gate button | consequence prompt + confirmation |
| Dissent | persistent report panel | report section immediately after majority |
| Asset slots | optional mark/frame/context region | text attribution only; no image protocol |
| Alert | semantic region + text + icon | `ALERT` label + text; optional ANSI red |

Terminal clients do not display inline official raster art through proprietary
terminal image protocols. A licensed mark may be represented by approved text or
original ASCII only when the authorization covers that representation.

## Prototype fixture

`apps/web/wireframes/ui-d2.html` provides a browser-viewable, dependency-free
fixture for inbox, confirmation, run, review, report, and recovery layouts. It uses
only placeholders and synthetic decision data. It does not call the API, imply a
permission, or ship through the production Web server.

## Confirmed UI-D2 decisions

1. Accept the wide Web three-region shell and single-column responsive order.
2. Accept the persistent five-section workspace navigation.
3. Accept the state module above content and the action gate after consequence copy.
4. Accept equal three-perspective diagnostics and the preliminary review treatment.
5. Accept optional licensed-asset slots with a fully functional original fallback.
6. Accept terminal breakpoints and confirm-before-mutation keyboard behavior.

These six decisions are frozen. UI-D3 may tune visual expression and component
anatomy without changing their information order or interaction semantics.
