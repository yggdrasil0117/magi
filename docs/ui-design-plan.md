# MAGI UI/UX delivery plan

Status: UI-D1 structure pending confirmation; EVA-inspired visual direction required

## Product objective

The interface should make a complex decision inspectable without making it feel
like a dashboard for agent internals. A user must always be able to answer:

1. What decision is being made and which version is active?
2. What does MAGI know, what is assumed, and what is missing?
3. Is the system waiting for me, working, complete, or unable to decide?
4. What did the majority conclude, and what dissent was preserved?
5. Which evidence and audit records support the displayed result?

The UI never calculates votes, upgrades evidence quality, changes a state, or
turns a non-decisive result into a recommendation.

## Shared information architecture

The full client will use these top-level areas:

- Decision inbox: authorized decisions, current state, version, and required action.
- New decision: question, options, constraints, risk floor, classification, and evidence.
- Confirmation: normalized case diff, unknowns, evidence boundary, and explicit approval.
- Live run: stage progress and agent availability without partial vote disclosure.
- Final report: outcome, vote count, majority rationale, dissent, risks, conditions,
  missing information, next step, and review audit.
- Evidence: provenance, verification, capture time, classification, hash, and citations.
- History: append-only public events, revisions, comparisons, and exports.
- Settings: API connection, session authentication, locale, theme, and accessibility.

## State design matrix

| State | Primary message | Primary action | Forbidden presentation |
|---|---|---|---|
| created / normalized | Draft is still editable | Continue preparation | Imply that agents voted |
| waiting_for_user | Case needs confirmation | Confirm or cancel | Hide normalized changes |
| evidence_ready | Case is frozen, run not started | Start or cancel | Start automatically |
| first_ballot | Independent voting in progress | Wait | Show partial votes |
| cross_review | One bounded review in progress | Wait | Show partial review ballots |
| completed | Final report is authoritative | Inspect or export | Hide minority report |
| insufficient_information | More evidence is required | Review missing information | Display a winner |
| degraded | A perspective is unavailable | Inspect limitations | Present two votes as official |
| failed | Protocol did not complete | Inspect failure and retry policy | Invent a fallback result |
| cancelled | User stopped the workflow | Return to history | Offer run/confirm actions |

Denied, not-found, report-not-ready, offline, timeout, malformed-response, empty,
and first-load states receive distinct copy and recovery actions.

## Design system foundations

- Semantic tokens: surface, text, border, focus, informative, success, caution,
  danger, and perspective identity. Status always includes text and structure.
- Typography: readable UI face plus restrained monospace for IDs, evidence refs,
  versions, timestamps, and machine states.
- Components: state banner, decision header, action bar, option list, evidence row,
  agent progress card, vote summary, minority panel, audit timeline, confirmation
  diff, error recovery panel, and export menu.
- Layout: responsive from 360 px upward, with report reading width constrained and
  dense evidence/audit tables able to collapse into labelled cards.
- Motion: short and informational only; honor reduced-motion preferences.
- Accessibility target: WCAG 2.2 AA for Web, full keyboard operation, visible focus,
  logical heading order, labelled inputs, live-region restraint, and non-color cues.
- Content: concise Chinese first, with layouts tested for English expansion and
  machine identifiers that must not wrap ambiguously.

Visual direction is constrained by `docs/ui-visual-direction-eva.md`: an original
EVA/MAGI-inspired command interface using operational amber, state-only red alerts,
severe geometry, technical indexing, and three-system composition. Accessibility
and readability override decorative similarity.

## Medium-specific behavior

### Web

Use responsive hierarchy, progressive disclosure, side-by-side comparison when
space permits, and explicit confirmation dialogs for state-changing commands.
Credentials stay in memory unless a later security design authorizes another
storage mechanism. External content enters text-only DOM nodes.

### Terminal TUI

Use predictable keyboard navigation, command palette help, persistent state and
connection indicators, scrollable evidence/report panes, and a no-color mode.
External control characters are removed. Screen layouts prioritize meaning over
imitating the Web page.

### CLI

Keep stable JSON, non-ANSI redirected output, deterministic field names, and
documented exit codes. CLI automation must not depend on visual wording.

## Staged confirmation gates

### UI-D1: journeys and information architecture

Deliver user flows, the state matrix, screen inventory, and permission boundaries.
Confirm scope and navigation before drawing detailed screens.

Proposal: `docs/ui-d1-information-architecture.md`.

### UI-D2: low-fidelity interaction design

Deliver Web wireframes and terminal wireframes for create, confirm, run, report,
evidence, history, and all failure states. Confirm field priority and actions before
choosing final visual styling.

### UI-D3: visual foundation and component contract

Deliver color and typography tokens, spacing, component anatomy, responsive rules,
focus behavior, content guidelines, and representative high-fidelity screens.
Confirm one visual direction before production component work.

### UI-D4: implementation

Build shared contract tests, then TUI workflow, Web workflow, and CLI automation.
No client may bypass the API or import agent/orchestration implementations.

### UI-D5: acceptance

Test representative users and keyboard-only flows; run accessibility checks; verify
small, medium, and wide layouts; validate every state; and prove cross-client
semantic parity from versioned fixtures.

## Immediate next design decision

Confirm structural decisions 1–4 at the end of the UI-D1 proposal before producing
UI-D2 wireframes. The visual intent is already constrained to the original
EVA/MAGI-inspired direction; UI-D2 will translate it into layout without freezing
final components or styling.
