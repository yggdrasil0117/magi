# UI-D5 acceptance

Status: passed

Acceptance evidence includes:

- every authoritative decision state is exercised by versioned fixtures;
- partial ballots remain sealed before the disclosure boundary;
- Web inputs are labelled, keyboard landmarks and visible focus are present;
- 360 px, 520 px, 800 px, and wide layouts have explicit responsive treatment;
- reduced-motion preference disables decorative motion;
- production assets are same-origin and no third-party licensed fixture is loaded;
- bearer tokens remain memory-only across Web, terminal, and CLI;
- operation and decision discovery are principal scoped and re-authorized;
- terminal failures are sanitized and output remains no-color;
- CLI output is deterministic JSON with stable exit-code families;
- Web, TUI, and CLI consume public API projections without importing agents,
  orchestration, checkpoints, or arbitration.

Automated suites cover model validation, API authorization, persistence boundaries,
proxy allowlists, Web sanitization, responsive/accessibility invariants, terminal
failure handling, and CLI schema behavior. Real PostgreSQL/OpenAI acceptance remains
environment-gated and is not represented as executed when credentials are absent.

Headless Chromium renders were also inspected at 1440×1000 and 390×844. The wide
layout preserves the three-column command composition; the compact layout collapses
to a readable single-column flow without horizontal overflow. These temporary QA
captures are intentionally excluded from the repository.
