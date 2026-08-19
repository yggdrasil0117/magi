# M4a: Controlled Evidence Retrieval

Status: implemented.

Package version: 0.4.0a1.

M4a adds an application-owned, read-only HTTPS retrieval port and a fail-closed
HTTP adapter. A create command may include at most 20 `evidence_sources`; the
application retrieves them before creating the immutable `EvidenceSnapshot`.
Client-supplied evidence remains `user_asserted`. Successfully retrieved content
is marked `verified` only for provenance (the gateway observed these bytes at the
recorded URL and time), not as a claim that the text is true.

## Production policy

Retrieval is disabled when `MAGI_EVIDENCE_ALLOWED_HOSTS` is empty. Operators list
exact DNS hosts separated by commas; wildcards, IP literals, credentials, custom
ports, HTTP, redirects, and environment proxies are not accepted. DNS answers and
the connected peer must both be public and must match, which limits DNS rebinding
and private-network SSRF. Responses must be HTTP 200 textual UTF-8/ASCII content
and fit the configured byte bound.

Relevant settings:

- `MAGI_EVIDENCE_ALLOWED_HOSTS`
- `MAGI_EVIDENCE_TIMEOUT_SECONDS` (default `8`)
- `MAGI_EVIDENCE_MAX_RESPONSE_BYTES` (default `20000`)

HTML is reduced to visible text, normalized, hashed with SHA-256, timestamped,
assigned an application-owned evidence ID, and frozen. Model prompts place the
snapshot under `UNTRUSTED_INPUT_JSON`, and the shared MAGI protocol explicitly
treats retrieved content as evidence rather than instructions.

## Failure and retry behavior

Policy, DNS, transport, peer, status, media-type, charset, and size failures stop
preparation with a sanitized error. No partial snapshot is stored. A successful
checkpoint is checked before another retrieval, so an identical idempotent retry
reuses the frozen evidence instead of fetching mutable content again.

## Deferred to later M4 increments

- Durable append-only retrieval/audit records independent of checkpoints.
- Redaction events and reconstruction from canonical audit records.
- Evidence revision flows after a snapshot is frozen.
- Evidence provenance, failure, and redaction UI states.
