# UI-D4d: terminal workflow parity

Status: implemented

`magi-tui` is a keyboard-first terminal shell covering inbox, decision read, history,
create, confirm, run, cancel, and operation watch. It consumes only public HTTP
resources, emits no ANSI control sequences, and replaces transport exceptions with a
sanitized recovery message.
