# CLI client

The `magi` CLI provides stable JSON automation over public API contracts. It does
not calculate votes or arbitration status locally.

~~~text
magi inbox [--limit N]
magi get DECISION_ID [--version N]
magi history DECISION_ID
magi create QUESTION [--risk LEVEL] [--classification CLASS]
magi confirm DECISION_ID --at ISO_TIMESTAMP [--version N]
magi run DECISION_ID [--version N]
magi cancel DECISION_ID [--version N] [--reason TEXT]
magi watch OPERATION_ID
~~~

Mutation commands accept `--idempotency-key KEY`. Automation should reuse the same
key after an unknown outcome; `MAGI_IDEMPOTENCY_KEY` provides the equivalent
environment setting. A random key is generated only when neither is supplied.

Exit codes are `0` success, `2` usage, `3` authentication/authorization, `4`
conflict, and `5` transport/server failure. Output is UTF-8 JSON with deterministic
key ordering and no ANSI sequences.
