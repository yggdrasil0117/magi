# Web report viewer

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

M3c provides a dependency-free report viewer that consumes the same authenticated
JSON report as the terminal client. It uses DOM `textContent` for external prose,
keeps the bearer token only in page memory, and never calculates a vote or status.

Start MAGI's API, then run:

~~~powershell
$env:MAGI_API_URL = "http://127.0.0.1:8000"
node apps/web/server.mjs
~~~

Open `http://127.0.0.1:3000`. The local server binds only to loopback and proxies
only final-report reads, so the production API does not need a permissive CORS
policy. Static and proxied responses include a restrictive CSP and no-store
headers.

The full Next.js workflow, history, and revision comparison remain planned for
M5. This M3 surface intentionally proves report parity without expanding scope.
