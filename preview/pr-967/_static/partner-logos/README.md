<!--
SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
SPDX-License-Identifier: Apache-2.0
-->

# Partner logos

Canonical card logos for the Ecosystem page. Referenced by `logo.src` in
`docs/source/_data/partners.yaml`; a record with no `logo` key renders the
organization name as a plain text wordmark instead, which is what every card does
today — this directory is empty on purpose.

- Name files after the partner `id`, e.g. `acme.svg` and `acme-dark.svg`.
- Prefer approved SVG artwork. Use PNG only when no vector asset exists; never JPEG.
- Preserve brand colors, proportions, and required clear space. Do not recolor or
  redraw a mark to fit — the card's logo panel is a fixed 104px box and CSS scales
  artwork to fit it.
- SVGs here are exempt from Git LFS (see `.gitattributes`), so keep them small and
  text-based; strip editor metadata before committing.
- Record the source and any attribution or usage restriction alongside the partner's
  record in `partners.yaml` when the license requires it.
