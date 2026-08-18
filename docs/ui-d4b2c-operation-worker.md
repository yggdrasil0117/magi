# UI-D4b-2c: recoverable operation worker

Status: implemented

The worker executes durable create/run operations outside the HTTP request lifecycle.
It reuses `DecisionApplicationService`, so the asynchronous path does not create a
second decision engine or bypass LangGraph checkpoints.

## Safety boundary

- A claim changes `accepted` to `running` and appends its public event atomically.
- PostgreSQL `FOR UPDATE SKIP LOCKED` distributes queued work without blocking peers.
- A session advisory lock remains held for the entire execution.
- Every claim increments a fencing token. Renewals, progress, success, and failure
  updates require both the current token and a hashed worker identity.
- A terminated worker does not manufacture a failure. Once its lease expires, a new
  worker can reclaim the operation and receives a newer fencing token.
- Client-visible failures use a stable code; internal exception text is never stored.
- Operation state and its public event are committed in the same transaction.

## Execution mapping

- `create_decision` validates the stored payload as `DecisionPreparationRequest` and
  calls `DecisionApplicationService.prepare`.
- `run_decision` calls `DecisionApplicationService.run` for the stored identity.
- Successful execution emits `reporting` and then `complete`; ordinary execution
  failure emits a sanitized terminal failure.
- Cancellation and lost leases escape the worker without writing a false terminal
  result.

## Deployment note

Each active worker holds one database connection while executing. Production sizing
must reserve pool capacity for workers, LangGraph checkpoints, and invocation-ledger
writes. D4b-2d will expose acceptance, status, result, and replay resources; it will
not start work inside an HTTP handler.
