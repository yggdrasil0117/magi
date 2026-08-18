# UI-D4 production implementation plan

Status: UI-D4 complete; UI-D5 acceptance complete

## Scope rule

Production clients consume only authenticated API resources and sanitized shared
projections. They do not import orchestration, agent, checkpoint, or arbitration
implementations. A missing API contract produces an explicit unavailable state;
fixtures never masquerade as production records.

## Increment map

| Increment | Deliverable | Required contract |
|---|---|---|
| UI-D4a | Read-only Web decision workspace, case/evidence/perspective/report states | Existing `GET DecisionView` and report projection |
| UI-D4b | Create, confirm, run, cancel and reconnectable command UX | Existing commands plus verified capability projection |
| UI-D4c | Authorized inbox, revisions, event replay and history | New list, revision and public-event APIs |
| UI-D4d | TUI workflow parity | Frozen Web semantics and same API contracts |
| UI-D4e | CLI workflow automation | Stable command schemas, JSON and exit codes |

UI-D4a is intentionally useful without inventing the future inbox: a user opens a
known authorized decision by ID and version, using a bearer token kept only in page
memory. The same screen renders all current authoritative states.

## UI-D4a Web contract

- the loopback Web service proxies only allowlisted decision GET resources;
- upstream base URL rejects embedded credentials, search, and fragments;
- bearer tokens are forwarded for the current request and never logged or stored;
- response size is bounded and cache headers are `no-store`;
- external strings enter the DOM through `textContent` only;
- `DecisionView.schema_version` must be `1.0` and required fields are validated;
- the client displays actions only from `available_actions`, without inferring them;
- first-ballot states never render ballot contents even if malformed upstream data
  includes them; cross-review labels released ballots as preliminary;
- terminal results reuse the existing `DecisionReport` renderer, preserving dissent;
- unknown states and malformed documents fail closed into a recovery panel.

## Current contract gaps

UI-D4a does not fabricate these capabilities:

1. authorized decision list and required-action counts;
2. policy-safe capability discovery before a decision is loaded;
3. edit and explicit prepare boundaries;
4. create-new-version command and ancestry;
5. reconnectable public event replay/stream;
6. complete evidence provenance and audit resources from M4.

UI-D4b may use current command actions after a separate confirmation of mutation
copy, idempotency-key lifetime, double-confirm behavior, and long-running run UX.
It must not infer broader permissions from a successful read.

## UI-D4a acceptance

- Web loads a real `DecisionView` through the loopback same-origin proxy.
- Waiting, ready, running, review, terminal, degraded, failed, and cancelled state
  families have explicit messages and visual treatment.
- Case options, constraints, unknowns, public evidence, released ballots, actions,
  and final report are mapped without calculating a result.
- Hidden ballot disclosure is enforced at the presentation boundary.
- Tokens live only in memory and no third-party resource request is introduced.
- Contract, sanitization, proxy-path, and existing report parity tests pass.

All UI-D4a acceptance items pass locally. The loopback server smoke confirms a 200
workspace response with `no-store` headers and rejects non-allowlisted API paths.

## UI-D4b decision gate

Before adding mutations, confirm this split:

1. UI-D4b-1 adds confirm and cancel using `available_actions`, an in-memory
   idempotency key, consequence copy, and a second explicit confirmation.
2. UI-D4b-2 adds create and run only after choosing the long-running command model.
   The current API holds the HTTP request until Coordinator/model work completes;
   the planned public event/replay contract would support safer reconnect behavior.
3. Until capability discovery exists, global create cannot be shown based solely on
   a successful decision read; its permission must be configured explicitly or the
   backend must expose a policy-safe capability projection.

This prevents a short browser timeout from being mistaken for command failure and
then issuing a second model run under a new key.

## UI-D4b-1 implementation

UI-D4b-1 is implemented with these boundaries:

- only `confirm` and `cancel` controls declared by `available_actions` are active;
- every mutation opens a modal with the decision/version and plain-language effect;
- confirm freezes one timezone-aware timestamp and explicitly does not start models;
- cancel accepts an optional reason, trims control characters, and preserves history;
- the browser creates a cryptographically random in-memory idempotency key per
  confirmed intent and freezes its request body;
- a timeout or unknown outcome retains that exact key and body for retry; the user
  may abandon the local retry only after being told to resynchronize server state;
- a different mutation cannot be created while an unknown intent remains pending;
- the loopback proxy permits POST only for UUID-scoped `confirm` and `cancel`, caps
  request bodies at 10 KB, and continues to reject create and run;
- successful commands render the returned `DecisionView` immediately.

UI-D4b-2 selected an accepted command receipt plus public event/status replay for
reconnect safety while preserving synchronous compatibility.

The accepted durable receipt and replay option is specified in
`docs/ui-d4b2-async-operations.md`. Application-level receipt/event models and
fail-closed lifecycle tests are present. PostgreSQL operation/event persistence is
implemented in D4b-2b. D4b-2c implements recoverable leased execution with
fencing-token protected writes. D4b-2d activates opt-in async submission,
owner-scoped polling, public event replay, OpenAPI contracts, and the production
worker lifecycle.

UI-D4b-2e connects those resources to the production Web workspace: explicit
asynchronous create, guarded asynchronous run, stage/event monitoring, and refresh
recovery by opaque operation ID. Bearer credentials remain memory-only.

UI-D4c-1 adds the first discovery surface: a principal-scoped operation inbox with
active/failed counts and recent receipts. UI-D4c-2 separately adds the decision/version
catalog so the UI does not infer decision history from operation history.

UI-D4c-2 adds a principal-scoped decision catalog, required-action count, and ordered
version history backed by a dedicated PostgreSQL projection. Synchronous API commands
and asynchronous worker completion both update the same projection. The Web history
surface compares authoritative `DecisionView` versions side by side.

UI-D4d provides a keyboard-first terminal workflow over the same authenticated HTTP
resources. It supports inbox, get, history, create, confirm, run, cancel, and watch,
sanitizes failures, and never imports orchestration or agent implementations.

UI-D4e provides the `magi` automation CLI with stable JSON output, public command
schemas, explicit asynchronous create/run, and documented exit-code families.

UI-D5 acceptance covers versioned state fixtures, hidden-ballot disclosure, keyboard
landmarks, labelled credentials, visible focus, reduced motion, responsive breakpoints,
same-origin assets, no-color terminal behavior, JSON stability, proxy allowlists, and
cross-client use of the same API projections.
