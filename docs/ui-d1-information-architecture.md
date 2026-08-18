# UI-D1: User journeys and information architecture

Status: accepted; structural decisions 1–5 confirmed

## Scope and decisions

UI-D1 defines where information lives, when it becomes visible, and which actions
are possible. It does not freeze colors, typography, component styling, or detailed
screen geometry; those belong to UI-D2 and UI-D3.

The proposal assumes a user may own or access multiple decisions, revisit earlier
versions, and use either Web or terminal without changing the authoritative state.

## Navigation model

Use a decision inbox plus one versioned decision workspace. Do not create separate
top-level destinations for agents: the three perspectives are evidence within a
decision, not independent chat products.

~~~mermaid
flowchart TD
    I["Decision inbox"]
    N["New decision"]
    W["Decision workspace (ID + version)"]
    O["Overview"]
    E["Evidence"]
    P["Perspectives"]
    R["Final report"]
    A["Audit and versions"]
    S["Settings"]

    I --> N
    I --> W
    W --> O
    W --> E
    W --> P
    W --> R
    W --> A
    I --> S
~~~

Web routes are proposed as:

- `/decisions`: authorized inbox and required actions;
- `/decisions/new`: decision preparation;
- `/decisions/{decision_id}/versions/{version}`: versioned workspace;
- workspace subsections: overview, evidence, perspectives, report, and audit;
- `/settings`: connection, session, locale, theme, and accessibility.

TUI uses the same hierarchy as screens rather than URLs. The default wide layout
has an inbox/navigation pane, a primary workspace pane, and a contextual action or
detail pane. Narrow terminals replace panes with a screen stack. This preserves
information architecture without forcing the Web layout into the terminal.

## Primary decision journey

~~~mermaid
flowchart LR
    Q["Enter question, risk floor, classification, evidence"]
    C["Coordinator normalizes case"]
    V["Review normalized case and differences"]
    F["Confirm and freeze"]
    G["Explicit run gate"]
    B["Independent first ballots"]
    X["Optional bounded cross-review"]
    D["Deterministic result"]
    R["Inspect report, evidence, dissent, and audit"]

    Q --> C --> V
    V -->|"Edit"| Q
    V -->|"Confirm"| F --> G
    G -->|"Start"| B
    B --> X
    B --> D
    X --> D --> R
~~~

The confirmation screen is mandatory and distinct from the creation form. It shows
the raw question beside the normalized question, options, constraints, unknowns,
risk, classification, and frozen evidence boundary. Confirmation and run remain
two separate user actions. Neither Web nor TUI may automatically advance them.

## Recovery journeys

### Missing information

An insufficient result opens the report at “Unresolved questions,” followed by
evidence gaps and the action to create a new version. The old version remains
immutable and readable. The UI must not relabel this state as rejection.

### Conditional rejection

Show the accepted constraint, reconsideration conditions, supporting evidence, and
new-version action. Do not display a winner or a generic red failure screen.

### Degraded or failed run

Show unavailable perspectives, the last trustworthy stage, retry policy, and audit
events. A degraded two-agent outcome is advisory and cannot use decisive styling.

### Resume and reconnect

After refresh, restart, timeout, or network loss, reload `DecisionView` and resume
from its server state. Never reconstruct progress from local timers. When state is
uncertain, disable mutations until the authoritative view is fetched again.

## Versioned workspace

### Overview

Always displays decision title, ID, active version, state, risk, classification,
question, options, constraints, unknowns, and the single primary action permitted
by `available_actions`. Cancellation is visually separate from the primary action.

### Evidence

Displays source, type, verification status, classification, capture time, hash, and
citation usage. Restricted evidence must never appear because it is removed before
`DecisionView`. M4 adds provenance, citation-validation, redaction, and retrieval
states without changing this location.

### Perspectives

Before first-round assessment, show only agent identity and progress state. During
cross-review, the already released first-round ballots may be shown under the
explicit label “First-round view — not final”; no partial review ballot is shown.
After arbitration, show final ballots, whether each perspective retained or revised
its vote, and the review reason. Do not expose private working memory.

### Final report

Prioritizes status and selected option, then vote count, majority rationale,
minority report, risks and conditions, missing information, recommended next step,
evidence references, and review audit. A non-decisive report uses state-specific
language and cannot display a selected option.

### Audit and versions

Shows append-only public events, command actor, timestamps, version lineage, and
comparison entry points. Raw prompts, credentials, provider messages, restricted
content, and hidden chain-of-thought never appear.

## Screen inventory

| Screen | Purpose | Authoritative source | Main actions |
|---|---|---|---|
| Sign-in / connection | Establish API session | Client configuration | Connect, disconnect |
| Decision inbox | Find work and required action | Future authorized list API | Open, create |
| New decision | Supply initial inputs | Create command schema | Submit, discard |
| Confirmation | Verify normalization | `DecisionView.case` and evidence | Edit, confirm, cancel |
| Run gate | Prevent automatic model use | `awaiting_run` and actions | Start, cancel |
| Live run | Communicate safe progress | State plus public events | Reconnect, wait |
| Decision workspace | Persistent version shell | `DecisionView` | State-dependent |
| Final report | Explain outcome and dissent | `DecisionReport` | Export, inspect evidence |
| Evidence detail | Inspect provenance/citations | Evidence and M4 audit APIs | Navigate only in v1 |
| Audit/history | Reconstruct and compare | Future events/version APIs | Filter, compare, export |
| Error/recovery | Provide a safe next step | Stable API error envelope | Retry, reconnect, return |
| Settings | Local preferences | Client-owned configuration | Save locally permitted prefs |

## State and disclosure contract

| State | Default workspace section | Visible decision records | Mutations |
|---|---|---|---|
| created / normalized | Overview | Editable case only | Edit, prepare, cancel |
| waiting_for_user | Confirmation | Case and public evidence | Confirm, edit, cancel |
| evidence_ready | Overview / run gate | Frozen case and evidence | Run, cancel |
| first_ballot | Perspectives | Progress only; no ballots | None |
| cross_review | Perspectives | Released first ballots; no review ballots | None |
| completed | Final report | Final ballots, result, report, audit links | New version only |
| insufficient_information | Final report / gaps | Result, missing information, ballots | New version only |
| degraded | Final report / limitations | Advisory result and unavailable agents | New version only |
| failed | Audit / recovery | Failure state and safe events | New version or retry policy |
| cancelled | Overview | Frozen last public state | None |

The client renders `available_actions`; it does not infer a legal action from the
state table. The table specifies UX intent and identifies contract gaps.

## Permission boundary

| Capability | Current authorization action | UI behavior |
|---|---|---|
| Create decision | `decision:create` | Global “New decision” action |
| Read workspace/report/export | `decision:read` | All non-mutating decision views |
| Confirm case | `decision:confirm` | Confirmation primary action |
| Start run | `decision:run` | Explicit run-gate action |
| Cancel unfinished decision | `decision:cancel` | Separated destructive action |
| Edit draft | Contract planned; action not implemented | Do not ship edit UI yet |
| Create revision | Contract planned; action not implemented | Do not ship revision UI yet |
| List authorized decisions | Endpoint planned; capability discovery absent | Use explicit unavailable state |

Interfaces must not discover permissions by optimistically issuing mutations and
waiting for a 403. Before UI-D4, the API needs an authorized capability projection
or equivalent policy-safe mechanism so controls can be presented accurately.

## Backend contracts required before full UI implementation

UI-D1 identifies these existing roadmap gaps; it does not authorize implementing
them in this design increment:

1. authorized decision list with state, version, updated time, and required action;
2. edit-before-freeze and explicit prepare boundaries;
3. create-new-version command with immutable ancestry;
4. public event replay/stream for reconnectable progress;
5. policy-safe capability discovery;
6. evidence provenance, citation status, redaction, and audit history from M4.

Until a contract exists, UI prototypes use labelled fixtures rather than fake
production behavior.

## UI-D1 acceptance checklist

- One workspace owns case, evidence, perspectives, report, and audit context.
- Confirmation and run are separate, explicit steps.
- Every domain state has a default message, location, action, and recovery path.
- First-round and review disclosure matches protocol secrecy boundaries.
- Majority dissent and non-decisive limitations remain first-class.
- Web and TUI share hierarchy and semantics without sharing screen geometry.
- Authorization and missing backend contracts are visible in the design.
- UI does not calculate status, votes, permissions, or legal transitions.

## Confirmed decisions

1. Adopt the decision inbox plus one versioned workspace as the primary structure.
2. Adopt five workspace sections: Overview, Evidence, Perspectives, Report, Audit.
3. Keep confirmation and explicit run as separate screens/actions.
4. Show released first-round ballots during cross-review only as clearly preliminary.
5. Use the EVA/MAGI-inspired command interface under the constraints in
   `docs/ui-visual-direction-eva.md` and `docs/ui-asset-governance.md`.

UI-D1 is accepted. UI-D2 may refine layout and interaction, but changing these
five decisions requires an explicit information-architecture revision.
