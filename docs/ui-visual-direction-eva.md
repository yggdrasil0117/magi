# MAGI visual direction: EVA-inspired command interface

Status: required product constraint; implementation begins in UI-D2/UI-D3

## Intent

The interface should feel recognizably related to the command, diagnostic, and
MAGI-computer displays associated with *Evangelion*. This is more specific than a
generic dark or cyberpunk theme: it uses an operational-control visual language,
high information hierarchy, severe geometry, and context-sensitive alarm states.

The result remains a MAGI product interface. It may provide controlled placements
for licensed NERV marks, character art, screenshots, slogans, or other supplied
materials. No official asset is bundled until its exact file and intended use pass
the provenance and permission gate in `docs/ui-asset-governance.md`.

Primary reference sources are the
[official Evangelion portal](https://www.evangelion.jp/) and its
[official production commentary](https://www.evangelion.jp/news/q3333_exposition/).
Fan recreations may help identify recurring patterns, but are not source assets and
must not become the implementation specification.

## Core visual grammar

### Color roles

- Base: near-black, warm charcoal, and low-reflectance panel surfaces.
- Primary information: amber and signal orange rather than the current cyan-first
  hierarchy.
- Critical alarm: saturated red, reserved for failed, denied, destructive, or
  genuinely unsafe conditions.
- Nominal confirmation: constrained green used for verified/ready states.
- Secondary data: warm off-white and muted grey.
- Perspective accents: three related but distinguishable signal tones, always paired
  with MELCHIOR, BALTHASAR, and CASPER text labels or symbols.

The product must not stay in permanent red-alert mode. Ordinary reading uses dark
surfaces and amber information; alert treatment is a meaningful state transition.

### Geometry

- Asymmetric grids with one dominant region and smaller diagnostic regions.
- Heavy rules, cut corners, stepped frames, brackets, registration marks, and
  measured offsets.
- Diagonal caution bands only around destructive actions, hard constraints, and
  protocol failures.
- Oversized state words balanced by dense small metadata.
- Three-part structures for perspective status and review comparison; triangular
  composition may be used when it does not harm reading order.

Decorative frames cannot reduce the usable content width or create false controls.

### Typography and labels

- Condensed industrial sans-serif for headings and large status words.
- Monospace for IDs, versions, timestamps, evidence refs, vote counts, hashes, and
  protocol states.
- Readable Chinese sans-serif for paragraphs and decision reasoning; do not simulate
  Japanese text or replace meaningful Chinese labels with decoration.
- Uppercase English micro-labels, numeric section indices, coordinate-like markers,
  and terse status codes may support hierarchy.
- Human-facing explanations remain plain language beneath the technical label.

### Information density

EVA-like density is created through hierarchy, not by adding meaningless numbers.
Every technical label must represent a real field, state, version, permission, or
time. Decorative telemetry, fake progress percentages, and invented system metrics
are forbidden.

### Motion and sound

- Short scan, acquire, confirm, and alert transitions may reinforce real state
  changes.
- No continuous flicker, strong CRT distortion, rapid flashing, or ambient alarm
  sound in normal operation.
- Honor reduced-motion preferences and provide complete operation without sound.
- A future sound layer requires a separate mute, volume, and accessibility decision.

## State-specific expression

| State family | Visual expression |
|---|---|
| Draft / confirmation | Amber framing, editable markers, clear unconfirmed label |
| Ready to run | Structured gate panel with explicit armed-but-not-started message |
| First ballot | Three sealed status modules; no votes or fake percentages |
| Cross-review | Three linked modules plus “first round — not final” treatment |
| Consensus / majority | Stable amber structure with restrained green confirmation |
| Unresolved / insufficient | Amber caution, missing-information block, no winner |
| Conditional rejection | Caution geometry and reconsideration-condition emphasis |
| Degraded | Incomplete three-module structure with absent perspective named |
| Failed / denied | Red alert region, clear cause class, safe recovery action |
| Cancelled | Muted shutdown state without failure alarm language |

## Three-perspective identity

The visual system should make the three-personality architecture visible without
turning agents into chat avatars:

- MELCHIOR: analytical structure, evidence, feasibility, and uncertainty;
- BALTHASAR: safety, impact, reversibility, and constraints;
- CASPER: strategy, alternatives, and long-term effects.

Each perspective receives a consistent code, accent, and geometric marker. The
three modules have equal voting prominence. The Coordinator and deterministic
arbiter are displayed as process roles, never as a fourth personality.

## Web implementation rules

- Preserve the UI-D1 information architecture and responsive reading order.
- Use CSS design tokens for operational, caution, alarm, nominal, and perspective
  roles; do not hard-code red/orange into individual components.
- On small screens, collapse diagnostic regions into labelled sections rather than
  shrinking dense desktop panels.
- Use text-only DOM insertion for external content and keep the restrictive CSP.
- Provide a low-intensity reading mode if the full command-interface treatment
  reduces sustained report readability.

## Terminal implementation rules

- Reproduce hierarchy with spacing, rules, brackets, section codes, and optional
  ANSI—not with an exact copy of the Web geometry.
- Default color mapping follows amber/black, restrained green, and state-only red.
- Preserve complete no-color output and remove external terminal controls.
- The three perspective modules must remain understandable below 80 columns.

## Asset and originality boundary

Allowed inspiration includes operational density, amber/red-on-dark contrast,
non-rectangular framing, technical indexing, warning hierarchy, and three-system
composition. Unlicensed builds use original icons, copy, geometry, and repository
assets. Licensed builds may replace declared slots with approved official material.

User approval of a design direction is not evidence of copyright or trademark
permission. Downloading an official file does not grant redistribution rights.
Unverified material remains a labelled placeholder and is excluded from release
artifacts. Public or commercial distribution also requires a trademark and
visual-similarity review; the interface must not imply official endorsement unless
that representation is explicitly licensed.

## UI-D2 and UI-D3 deliverables

UI-D2 must produce each core screen in both Web and terminal wireframes using this
hierarchy: command header, state module, primary content, diagnostics, and action
gate. UI-D3 then freezes tokens, typography, frame primitives, icons, motion, and
representative high-fidelity screens.

Accessibility and authoritative state disclosure override visual similarity. If an
EVA-like treatment obscures dissent, evidence, focus, or recovery, it must be
simplified rather than preserved.
