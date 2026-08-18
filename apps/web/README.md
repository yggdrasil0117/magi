# Web report viewer

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
