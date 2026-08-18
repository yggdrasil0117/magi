# Terminal report client

M3c provides the first keyboard-friendly terminal surface through the
`magi-report` command. It reads the authenticated final-report API and renders
every authoritative report section without importing agent, orchestration, or
arbitration code.

~~~powershell
$env:MAGI_API_URL = "http://127.0.0.1:8000"
$env:MAGI_API_TOKEN = "your-token"
magi-report DECISION_UUID --version 1
~~~

During source development, the equivalent command is
`python -m magi.clients DECISION_UUID --version 1`.

Use `--json` for the unchanged report document or `--no-color` for stable plain
text. Redirected output automatically disables ANSI styling. Exit codes are 0
for decisive reports, 2 for advisory/non-decisive reports, 3 for degraded runs,
4 for failed runs, and 5 for client or transport errors.

The full interactive Textual workflow remains planned for M5.
