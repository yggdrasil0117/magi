# Web decision workspace

UI-D4a upgrades `/` from the M3 report-only surface to a real
`DecisionView` workspace. Enter a known decision ID, version, and bearer token to
render authoritative case, evidence, disclosed perspectives, available actions,
and the final report. UI-D4b-1 adds confirm and cancel only when declared by
`available_actions`; both use a consequence dialog, second confirmation, frozen
in-memory idempotency intent, and same-key retry. The token stays in page memory.
The page does not fabricate an inbox, create permission, or run behavior.

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
decision and final-report reads, so the production API does not need a permissive
CORS policy. Static and proxied responses include a restrictive CSP and no-store
headers.

Create/run, authorized inbox, history, and revision comparison remain separate
UI-D4 increments because long-running and discovery contracts must be accepted
independently.
