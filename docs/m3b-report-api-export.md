# M3b: Report API and export boundary

Package version: 0.3.0a2

## Delivered routes

- `GET /v1/decisions/{decision_id}/report?version={n}` returns the authoritative
  `DecisionReport` JSON schema.
- `GET /v1/decisions/{decision_id}/report.md?version={n}` downloads a deterministic
  Markdown rendering of the same report.

Both routes authenticate the bearer credential and apply the existing
`decision:read` permission for the requested decision. Export does not reveal
additional fields, so it does not create a broader authorization capability.

An unfinished, cancelled, or otherwise report-less decision returns HTTP 409 with
the stable `report_not_ready` code. Missing decisions remain 404, denied decisions
remain 403, and stored-record integrity failures remain sanitized 409 responses.

## Export safety

The Markdown renderer has no model boundary and does not read checkpoint state.
It accepts only a validated `DecisionReport`, emits fields in a fixed order, and
sorts vote-count keys. Model- or user-derived prose is flattened to one line and
Markdown control characters are escaped.

Downloads use a UUID-and-version filename, `text/markdown`,
`Content-Disposition: attachment`, `X-Content-Type-Options: nosniff`, and
`Cache-Control: private, no-store`. The JSON report uses the same cache and sniffing
controls.

## Deferred to M3c

- terminal report presentation;
- Web report presentation;
- parity acceptance proving both clients consume the same report resource.
