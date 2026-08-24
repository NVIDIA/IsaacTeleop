<!--
SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
SPDX-License-Identifier: Apache-2.0
-->

# Schemas and their golden binary form

[`fbs/`](fbs) holds the FlatBuffer schemas, this module's language-neutral contract.
Each binding generates its own code from them.

[`golden/`](golden) holds one `.bfbs` per schema, as those schemas compiled at the last
agreed revision. These are byte-for-byte the bytes `McapTrackerChannels` embeds in every
recording, so an existing `.mcap` on disk carries one of them.

They are deliberately **not** in LFS, unlike the binary assets in `.gitattributes`. Every
build reads them, and a clone that skipped `git lfs pull` would hand the test a pointer
file to parse as a schema — reported as an unparseable schema rather than a missing
fetch. At a couple of KB each, changing only when a schema does, plain git objects cost
nothing.

The `[schema_conform]` cases in `schema_tests` compare what the schemas compile to *now*
against the goldens, and fail when a change would make existing recordings unreadable.
That is the build-time half of the check `McapTrackerViewers` performs at replay time;
both call `check_schema_compat()`, so they agree on what "unreadable" means.

## Adding a field

Append it to a table with a fresh `id`. The test passes, and no golden needs to change —
a golden that is *older* than the current schema is exactly what it is for.

## When the test fails

It is telling you that recordings made before your change can no longer be read
correctly. Reach for one of these, roughly in order of preference:

- **Append instead of edit.** A new table field with a fresh `id` is always safe.
- **Deprecate instead of delete.** Mark the field `(deprecated)` rather than removing it,
  so the ids after it keep their slots.
- **Never change a `struct`.** Structs are stored inline with no vtable, so their size
  is baked into every layout enclosing them. Resizing one silently misreads any struct
  it is nested in and any vector of it, and reads past the end of the recorded value
  where it is a table field. Add a new optional *table* field instead.

## Refreshing the goldens

Only once the break is intentional and accepted:

```bash
cmake --build build --target schema_golden_update
```

That copies the freshly built `.bfbs` over [`golden/`](golden). Commit the result
together with the schema change, and say in the commit message what stops reading.
