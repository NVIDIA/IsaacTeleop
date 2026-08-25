---
description: >
  Write a single concise report.md for a completed device-onboarding run. Works from
  the agent's own memory (if you just did the work) or from collected artifacts
  (trajectory.jsonl, run.patch, diff_stat.txt). Tables over prose; one file only.
---

<!-- SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved. -->
<!-- SPDX-License-Identifier: Apache-2.0 -->

# Report a Run - Phase 3

Produce `report.md` — one file, skimmable, complete.

## Source

**Mode A — you did the work (same session):** write from memory. Cross-check against
`run.patch` / `diff_stat.txt` if present to catch any shared files you touched.
Cost is typically unavailable for self-report — say so rather than guessing.

**Mode B — past run (from artifacts):** read `trajectory.jsonl` for cost and decisions,
`diff_stat.txt` / `run.patch` for touched files, `plugin/` for symbols.

## Cost (Mode B)

If the trajectory has a final `type:"result"` record, read `total_cost_usd`, `usage`
(input/output/cache-read/cache-write tokens), `num_turns`, `duration_ms` directly.
Otherwise sum `usage` over assistant records and price with the model's public rates (state them).

## report.md structure

```markdown
# <Device> Onboarding — Report

**Device:** `<slug>` (<name>) · **Direction/Delivery:** <input / native|push|inject>
**Agent/Model:** <agent> · <model> · **Date:** <YYYY-MM-DD>

<One paragraph: what the device is, what was created vs reused, headline result.>

## Cost
| in | out | cache r/w | total $ | turns | wall time |
|---|---|---|---|---|---|
| … | … | … | $… | … | …s |
<rates used, or "unavailable for self-report">

## Verification ladder
| # | stage | command | result |
|---|---|---|---|
| 1 | build | `cmake --build build` | ✅ / ⚠️ |
| 2 | unit  | `ctest -R <device>` | ✅ N/N |
| 3 | runtime | `python examples/oxr/python/live_<device>.py` | ⚠️ not run — <why> |
| 4 | e2e | `python examples/oxr/python/test_<device>.py` | ⚠️ not run — <why> |
| 5 | finish | `cmake --build build` · `ctest --output-on-failure` | ✅ N/N |

## Files — with symbols
| file | symbols | status |
|---|---|---|
| `src/plugins/<device>/foo.cpp` | `FooPlugin`, `on_data()` | ✅ V — ctest -R foo passed |
| `src/core/.../bar.cpp` | `+FooRow` in dispatch | ✅ V — factory test |
| `src/plugins/<device>/main.cpp` | `main()` | ⚠️ NV — runtime only; run whole_pipeline |

## Roadmap
- **Searched/read:** …
- **Created:** … (code) · … (tests)
- **Edited:** …
- **Tested:** whole build ✅ · ctest N/N ✅ · stages 3–4 <status>

## Caveats
1. <what's unverified> — to close: `<exact command>`
```

## Rules

- **Every** touched file in the Files table — nothing omitted.
- `status` is `✅ V — <which check passed>` or `⚠️ NV — <why + command to close>`.
- A file is VERIFIED only by a check that **ran and passed** — "it compiles" = stage 1 only.
- No invented numbers. If data is missing, say so in one line.
- Write to `report.md` in the output folder (default: `./out/report.md`). Print the same content as the final message.
