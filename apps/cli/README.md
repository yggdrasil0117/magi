# CLI client

The `magi` CLI provides stable JSON automation over public API contracts. It does
not calculate votes or arbitration status locally.

~~~text
magi inbox [--limit N]
magi get DECISION_ID [--version N]
magi history DECISION_ID
magi audit DECISION_ID [--version N]
magi evaluations DECISION_ID [--version N] [--limit N]
magi evaluate DECISION_ID [--version N]
magi create QUESTION [--risk LEVEL] [--classification CLASS]
magi confirm DECISION_ID --at ISO_TIMESTAMP [--version N]
magi run DECISION_ID [--version N]
magi cancel DECISION_ID [--version N] [--reason TEXT]
magi redact DECISION_ID RECORD_ID JSON_POINTER --reason TEXT [--version N]
magi watch OPERATION_ID
~~~

Mutation commands accept `--idempotency-key KEY`. Automation should reuse the same
key after an unknown outcome; `MAGI_IDEMPOTENCY_KEY` provides the equivalent
environment setting. A random key is generated only when neither is supplied.

Exit codes are `0` success, `2` usage, `3` authentication/authorization, `4`
conflict, and `5` transport/server failure. Output is UTF-8 JSON with deterministic
key ordering and no ANSI sequences.

## Offline evaluation

`magi-eval BUNDLE.json [--fail-on-threshold]` evaluates sealed records without
calling the API or a model. It emits one stable JSON `DecisionEvaluation`.
Exit code `1` means a measured quality threshold failed; invalid or oversized
input returns `2`. Pricing is supplied in the versioned bundle and is never
inferred from a mutable provider price page.
