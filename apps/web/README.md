# Web decision workspace

UI-D4a upgrades `/` from the M3 report-only surface to a real
`DecisionView` workspace. Enter a known decision ID, version, and bearer token to
render authoritative case, evidence, disclosed perspectives, available actions,
and the final report. UI-D4b-1 adds confirm and cancel only when declared by
`available_actions`; both use a consequence dialog, second confirmation, frozen
in-memory idempotency intent, and same-key retry. UI-D4b-2e adds explicit async
create/run, public-stage monitoring, event replay, and recovery by opaque operation
ID. The token stays in page memory; only the non-secret operation ID may be retained
in session storage. UI-D4c adds authorized operation and decision inboxes, required
action counts, and version comparison. Create authority is enforced by the API,
not inferred by the page.

M4c adds a separately authorized audit-chain panel and append-only redaction
form. The panel renders verified sequence, phase, hashes, and redacted fields;
`audit:read` denial degrades locally without blocking the DecisionView. The
loopback proxy allowlists only the exact audit read and redaction paths.

## UI-D2 design fixture

`wireframes/ui-d2.html` is a dependency-free, browser-viewable proposal for the
future full decision workspace. Open the file directly in a browser. Its data is
synthetic, official-material regions are placeholders, and it is deliberately not
served by the production report proxy.

## UI-D3 visual prototype

`prototypes/ui-d3.html` applies the proposed visual tokens and component contract
to confirmation, completed-report, and degraded-recovery states. It includes an
original fallback mark, command/reading density controls, optional licensed-asset
slots, and responsive behavior. It is also synthetic and excluded from the
production report proxy.

The original M3 renderer remains the final-report component and consumes the same
authenticated report projection as the terminal client. External prose enters the
DOM through `textContent`; the Web client never calculates a vote or status.

Start MAGI's API, then run:

~~~powershell
$env:MAGI_API_URL = "http://127.0.0.1:8000"
node apps/web/server.mjs
~~~

Open `http://127.0.0.1:3000`. The local server binds only to loopback and allowlists
decision, report, and audit resources, so the production API does not need a permissive
CORS policy. Static and proxied responses include a restrictive CSP and no-store
headers.

Authorized inbox, history, and revision comparison are implemented through dedicated
principal-scoped API projections.

M5b allowlists the exact evaluation history/run resource through the loopback
proxy. No metric is calculated in the browser; the EVA-style evaluation panel
will consume this server-authoritative resource in M5c.
