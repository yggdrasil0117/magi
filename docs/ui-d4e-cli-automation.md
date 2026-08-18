# UI-D4e: CLI automation

Status: implemented

The `magi` command exposes stable JSON for inbox, get, history, create, confirm, run,
cancel, and watch. UUID arguments are validated before request construction. Create and
run explicitly request asynchronous execution. Exit-code families distinguish usage,
authorization, conflict, and transport failures without printing secrets.
