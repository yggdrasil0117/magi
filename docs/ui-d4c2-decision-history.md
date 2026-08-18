# UI-D4c-2: authorized decision catalog and history

Status: implemented

`magi_decision_catalog` is an explicit principal-scoped projection keyed by decision
and version. It is updated after synchronous commands and atomically with successful
asynchronous operation completion. The catalog API returns only the newest version of
each decision plus a required-action count; the history API returns validated
`DecisionView` versions newest first.

The Web catalog and comparison cards consume these resources directly. They do not
infer decisions from operation history, browser storage, or LangGraph internals.
