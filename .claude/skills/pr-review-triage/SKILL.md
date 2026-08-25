---
name: pr-review-triage
description: >-
  Triage automated review-bot feedback (CodeRabbit, code-quality bots) and human
  comments on an IsaacTeleop pull request. Use whenever asked to "check PR
  feedback", "address review comments", or re-check a PR after pushing fixes.
  Also use to sanity-check whether a finding fixed on one PR/branch applies to
  sibling PRs/branches (e.g. the same feature ported to release/1.4.x, or a
  near-identical device/plugin PR) before assuming it's isolated.
---

<!--
SPDX-FileCopyrightText: Copyright (c) 2025-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
SPDX-License-Identifier: Apache-2.0
-->

# PR review triage

A workflow for going through review comments on an IsaacTeleop PR (bot or human),
deciding what's real, and fixing only what's real — without re-litigating things
already fixed or chasing static-analysis false positives.

## 1. Fetch comments

`gh` in this environment is frequently unauthenticated for write operations, but the
public GitHub REST API works read-only without a token:

```bash
curl -s "https://api.github.com/repos/NVIDIA/IsaacTeleop/pulls/<N>/comments?per_page=100"
```

Pull `path`, `line`, `user.login`, `created_at`, `commit_id`, and `body` for each
comment. If `gh` write access is available, use it directly instead of drafting text
for the user to paste.

## 2. Classify each comment before touching code

For every comment, determine which bucket it's in — **do not start editing until
you've classified all of them**:

- **Already fixed / stale.** A comment's `commit_id` tracks the *current* diff
  position, not whether the finding is still valid — CodeRabbit updates this field on
  every push even for resolved findings. Read the current file at that location and
  compare against what the comment describes. If a prior commit already fixed it,
  it's stale; don't re-fix.
- **Already answered.** A design question a human or bot asked that a maintainer (you
  or someone else) already replied to in-thread. Don't re-answer unless new
  information changes the answer.
- **Static-analysis false positive.** Common patterns in this codebase that trip
  linters but are intentional:
  - Names in a module's `__all__` that aren't defined via a literal top-level
    `from x import y` — resolved instead through a lazy `_LAZY_IMPORTS` /
    `__getattr__` pattern (see any `retargeters/__init__.py`). Check whether the
    flagged name follows the same pattern as every *other* entry in that file; if so,
    it's a linter gap, not a bug.
  - A module imported once under `TYPE_CHECKING` (for a type hint) and once as a real
    lazy `import x as x` inside a function body (to defer loading a native/compiled
    module). Intentional in every `deviceio_source_nodes/*_source.py` file.
  - Verify by grepping for the same pattern elsewhere in the file/package before
    concluding it's a false positive — don't assume from one instance.
- **Real, in-scope bug.** Something this PR's diff introduced or should have caught.
  Fix it.
- **Real, but a pre-existing repo-wide convention.** The flagged code matches a
  pattern used elsewhere in the codebase *before* this PR (e.g. a comment template
  copied from a sibling schema file). Fixing only the files in this PR would create
  inconsistency with the rest of the repo. **Ask the user** whether to fix locally
  (accepting the inconsistency) or leave it and note a follow-up — don't decide
  unilaterally either way.
- **Real, but out of scope / correctly declined already.** E.g. a suggested fix that
  doesn't match this branch's actual build system (checked and verified, not assumed).
  If a maintainer already posted a reasoned decline in-thread, don't reopen it without
  new information.

## 3. Check sibling PRs/branches before fixing

IsaacTeleop device ports typically ship as parallel PRs: one feature × `main` and
`release/1.4.x`, or near-identical PRs for related devices (keyboard/gamepad/
spacemouse) built from the same template. A finding on one is very likely to exist
on all of them, because the code was copied, not independently written.

Before fixing only the PR you were asked about:

1. Identify the sibling branches (same feature on another release line, or
   copy-pasted device implementations).
2. Grep each sibling for the same code pattern (exact string match on the comment
   text, function name, or literal in question — not a re-read of the whole file).
3. Fix in every branch where it's present, not just the one that was flagged. Note
   in your summary which branches you checked and which had the issue.

## 4. Fix, build, test — per branch

For each affected branch/worktree:

1. Make the minimal fix.
2. Rebuild the affected target (`cmake --build . --target isaacteleop_python -j4` for
   a Python-only change; a bare `cmake --build . -j4` will also catch schema/codegen
   regressions but may hit unrelated pre-existing failures elsewhere in the repo —
   if so, fall back to the narrower target and note the unrelated failure rather than
   getting blocked by it).
3. Run the narrowest relevant `ctest -R <pattern>` first, then a wider sweep
   (`ctest -R "retargeting_test|schema_test"`) if the change touches shared
   infrastructure (tensor types, indices, source nodes).
4. Run `pre-commit run --files <changed files>` and re-run after any
   auto-reformat until clean.
5. Commit with `git commit -s` (sign-off required), imperative subject, no AI
   co-author line. Prefer one commit per logical fix over bundling unrelated fixes,
   matching this repo's existing history.
6. Push with `git push origin HEAD`.

## 5. Report back

Summarize per PR: what was stale/already-fixed, what was a false positive (and why),
what was fixed (with commit SHA), and what's still open pending a maintainer decision
(design questions, repo-wide convention conflicts). Don't fix and report in the same
breath if the user asked you to "check" or "analyze" first — respect a report-only
request before making changes.
