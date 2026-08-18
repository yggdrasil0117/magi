# UI asset governance

Status: required gate for every third-party or official asset

## Purpose

The product direction permits NERV marks, Evangelion screenshots, slogans,
characters, and other supplied material only when the exact use is authorized.
This document separates design approval from rights approval. It is an engineering
release control, not a legal opinion.

Studio Khara's published fan-work guideline is aimed at individual, basically
non-commercial fan publication; it says commercial or promotional use requires
individual permission, official source material must stay within quotation, and
work must not be presented in a way likely to be mistaken for official material.
Official store terms also reserve rights in its images and designs and prohibit
unauthorized copying or republication. Consequently, this repository does not
download, copy, or redistribute an official asset merely because it is visible on
an official website.

Primary references:

- https://www.khara.co.jp/guideline/
- https://www.khara.co.jp/contact/
- https://www.evastore.jp/shop/pages/terms.aspx

## Asset classes

| Class | Examples | Default repository behavior |
|---|---|---|
| Original | MAGI frames, icons, patterns, copy made here | May be committed with author/source record |
| Supplied and licensed | Rights-holder delivery or separately licensed file | May be committed only after manifest approval |
| Quotation candidate | Limited still/text excerpt used for criticism or reference | Legal review required; never treated as decoration |
| Personal-use-only | Wallpaper or download restricted to personal use | Never bundled or redistributed |
| Unknown | Web image, screenshot, logo file, fan upload, extracted frame | Placeholder only; reject from release |

## Required manifest record

Every non-original file needs one record before it can replace a wireframe slot:

~~~yaml
asset_id: eva-nerv-mark-primary
file: assets/licensed/eva-nerv-mark-primary.svg
sha256: "..."
rights_holder: "..."
source_url_or_delivery: "..."
license_or_permission_reference: "..."
authorized_product: "MAGI"
authorized_media: [web, terminal-docs]
authorized_territory: "..."
authorized_term: "..."
modification_allowed: false
attribution_required: "..."
official_endorsement_allowed: false
approved_by: "..."
approved_at: "YYYY-MM-DD"
notes: "..."
~~~

An empty, verbal, or generic value such as "user approved" does not satisfy
`license_or_permission_reference`. Permission must identify the rights holder or
an agreement whose scope covers the proposed product and distribution.

## Build and review gates

1. Design files refer to stable `asset_id` slots, never arbitrary web URLs.
2. Missing or unapproved assets render visible neutral placeholders in development.
3. Production builds fail when a configured official slot lacks a complete record,
   matching file hash, permitted medium, and active term.
4. Asset files are not loaded from third-party hosts at runtime.
5. Character art is contextual illustration, not an agent avatar, and cannot imply
   the fictional character produced the model's analysis.
6. Slogans are decorative labels only; safety instructions and actions retain plain
   Chinese wording.
7. Screenshots cannot sit behind report text unless contrast and cropping are
   separately approved; they never replace evidence or system status.
8. A release inventory lists included third-party assets, attribution, permission
   references, and expiration dates.

## Wireframe slots

UI-D2 reserves four optional slots without including protected material:

- `brand.primary_mark`: header mark, with original MAGI fallback;
- `scene.reference_frame`: low-priority contextual still, disabled by default;
- `perspective.context_art`: optional character/context panel, never a chat avatar;
- `copy.decorative_slogan`: non-instructional display copy.

The layout must remain complete when all four slots use their fallbacks. This keeps
the core application usable in open-source, personal, and licensed distributions.
