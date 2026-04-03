<!--
SPDX-FileCopyrightText: Copyright (c) 2025-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
SPDX-License-Identifier: Apache-2.0
-->

<!--
  MANDATORY FOR ALL AUTOMATED CODING AGENTS (Cursor, Copilot, etc.):

  Before modifying OR creating ANY file under this repository, you MUST use your
  file-reading tools to load EVERY AGENTS.md on the directory paths you will touch
  (see "CRITICAL — mandatory preflight" below). This is NON-OPTIONAL. Skipping it,
  or relying only on chat context without reading those files, is incorrect.

  Before you treat work as finished, you MUST run pre-commit as in
  "Pre-commit — match CI before you stop" and fix all failures. Declaring the task
  done without that run is incorrect.

  If pre-commit/CI fails, or the user corrects you, or you repeat the same class of
  mistake, you MUST record the lesson in AGENTS.md or source comments per
  "Mandatory learning loop" in the same session—not only when the user asks.

  Repository owners: keep this block at the top of this file; do not delete it.
-->

# IsaacTeleop — agent notes

## CRITICAL — mandatory preflight (do not skip)

**Hard requirement:** Do **not** edit or add code under `IsaacTeleop/` until you have **read** (e.g. with the Read tool) **every** relevant `AGENTS.md` file as defined below. This is **not** optional, **not** "only for large tasks," and **not** satisfiable by inferring from prior conversation. If you have not read those files in **this** session for **this** task, stop and read them first.

**You must:**

1. List the **directories** you expect to edit or create files under (e.g. `src/core/live_trackers/cpp/`, `src/core/deviceio_base/cpp/inc/…`).
2. For **each** such directory, **read** **`AGENTS.md` in that directory** if it exists.
3. Walk **up** toward the **IsaacTeleop repo root** and **read** **`AGENTS.md` in every ancestor directory** that has one (e.g. `live_trackers/` → `src/core/` → **`IsaacTeleop/AGENTS.md` (this file)**).

**You must not** assume that reading the single "closest" `AGENTS.md` is enough. **Multiple** `AGENTS.md` files can apply to one change (e.g. both `live_trackers` and `deviceio_base`).

**Listing every `AGENTS.md` in this repo** (no curated table here—add new files under the tree without editing this document):

```bash
# Run from the IsaacTeleop repository root (the directory that contains this file):
find . -name AGENTS.md ! -path '*/.git/*' | sort
```

If you cannot run a shell, use your search/glob tools on the pattern `**/AGENTS.md` from the same root. That inventory is for orientation; you must still **read** every file that applies to the directories you will touch (steps 1–3 above).

Optional context index: [`src/core/AGENTS.md`](src/core/AGENTS.md) (also on the ancestor walk—read it when working under `src/core/`).

## Pre-commit — match CI before you stop

- From the **IsaacTeleop repo root** (this directory), run pre-commit and **fix all failures** before you treat a change as finished (do not only rely on “should pass” reasoning).
- **Use the same hook set as GitHub Actions:** `.github/workflows/pre-commit.yaml` runs pre-commit with **`SKIP=check-copyright-year`**. Mirror that locally:

  ```bash
  SKIP=check-copyright-year pre-commit run --all-files
  ```

- **REUSE:** files covered by the REUSE hook need **`SPDX-FileCopyrightText`** and **`SPDX-License-Identifier`** in the form the repo already uses (for example the HTML comment block at the top of `README.md` also applies to **`AGENTS.md`** and similar docs).
- If a hook failure shows **missing or non-obvious repo policy** (not a one-off typo), you **must** add a **short** reminder under **Mandatory learning loop** rules to the right `AGENTS.md` or adjacent **`//` comments** so the next run does not repeat it—unless it is already documented.

## Mandatory learning loop (AGENTS.md and comments)

**Hard requirement:** When **any** of the following happens, you **must** complete steps 1–3 **before** you end the session or move on as if the work were complete:

1. The **user** is dissatisfied or corrects your approach (wrong layer, scope, style, or a fix that does not stick).
2. **Pre-commit** or **CI** fails on something you or another agent could hit again (linters, REUSE/SPDX, formatting, policy hooks, etc.).
3. You **repeat** the same **category** of error after a correction.

**You must:**

1. **Distill** what went wrong into a **short, reusable pattern** (a rule or boundary, not a chat transcript).
2. **Update** the right artifact in the **same working pass** as the fix: prefer the **most local** `AGENTS.md` for package- or subtree-level rules; use the **repo root** `AGENTS.md` only for expectations that span the whole tree; put **volatile or line-specific** detail in **`//` comments** next to the code.
3. Respect **scope vs `main`** (below): only add `AGENTS.md` bullets for **this branch’s delta** to **`main`** (or the agreed base), not for behavior that already exists on the base branch.

**You must not** skip documentation updates because the user did not say “update AGENTS.md”—failed checks and repeated mistakes **trigger** this loop automatically.

**What belongs in `AGENTS.md`**

- **High-level** expectations: boundaries between layers, what to avoid, naming or structural conventions, CMake/include policy at a glance, “always / never” rules that stay true across refactors.
- **Style of work**: how minimal to keep diffs, when to ask for clarification, how this subsystem should relate to OpenXR/schema/deviceio, etc.

**What does *not* belong in `AGENTS.md`**

- **Low-level or volatile detail**: exact call sequences, field-by-field semantics, long checklists tied to one function, anything that will go stale the next time the code moves.
- Put that in **comments in the source files** where the behavior lives (short `//` notes: intent, invariants, or “do not X because …”).

**Scope — document what *this* branch changes, not main**

- New or updated bullets should capture **learnings from the delta** between **this branch (or commit)** and **`main`** (or whatever long-lived base you are targeting—release branch, parent MR, etc.).
- Do **not** restate facts that already hold on **`main`** just because this branch touches nearby files. If behavior landed in the **base** history, it belongs in **code comments** next to that code or in **main’s** docs—not as “new” guidance in an `AGENTS.md` introduced only to support a smaller follow-up change.
- Example: schema- or API-level choices that merged **before** this branch are **out of scope** for `AGENTS.md` edits tied to this branch; they add churn and read like stale noise after merge.
