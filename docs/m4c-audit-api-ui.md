# M4c: Authorized Audit API and Client Surfaces

Status: implemented. M4 closes at package version 0.4.0.

M4c exposes the verified audit projection without weakening the M4b canonical
ledger. Audit access is separate from ordinary decision access:

- `GET /v1/decisions/{id}/audit?version=N` requires `audit:read`.
- `POST /v1/decisions/{id}/audit/redactions` requires `audit:redact` and an
  `Idempotency-Key`.

Both resources use private no-store responses. Redaction actor and command time
are server owned. A stable UUID derived from principal, decision ID, and the
idempotency key is stored instead of the raw key. Reuse with a different command
returns the standard idempotency conflict. Missing trails return a stable 404;
hash or sequence violations reuse the integrity-conflict response.

## Web

The EVA/MAGI-inspired workspace adds an `AUDIT CHAIN / 06` panel after the
authoritative report. It shows verified status, record sequence, kind, phase,
classification, timestamp, truncated hash, and redacted fields. Lack of
`audit:read` permission is an explicit local degradation and does not hide the
otherwise authorized `DecisionView`.

The redaction form requires a target record, simple JSON Pointer, reason, and an
explicit confirmation checkbox. It freezes its request and idempotency key for
safe retry, and states that canonical records are retained. The loopback proxy
allowlists only the two exact audit paths and continues to reject arbitrary
queries or mutations.

## Terminal and automation

The keyboard-first terminal adds `audit` and `redact` commands. The stable JSON
CLI adds equivalent commands for automation. Both call only the public API and
do not import or independently validate the decision engine.

## M4 acceptance

M4 now provides controlled read-only retrieval, frozen and hashed evidence,
citation boundary validation, append-only audit and redaction, report
reconstruction, explicit permissions, and matching Web/TUI/CLI audit states.
Deployment smoke with a real PostgreSQL service remains environment-gated.

