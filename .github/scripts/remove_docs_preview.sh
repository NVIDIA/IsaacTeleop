#!/usr/bin/env bash
# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
#
# Remove documentation previews from the gh-pages branch.
#
# remove_docs_preview.sh [pr-number ...]
#
# Several numbers are removed in one commit so the nightly sweep does not push
# once per stale preview. Idempotent: a missing branch or a missing directory is
# success, so it is safe to call speculatively. Callers that also push gh-pages
# should share a concurrency group.
set -euo pipefail

if [[ $# -lt 1 ]]; then
  echo "usage: remove_docs_preview.sh [pr-number ...]" >&2
  exit 1
fi
: "${GITHUB_TOKEN:?GITHUB_TOKEN is required}"
: "${GITHUB_REPOSITORY:?GITHUB_REPOSITORY is required}"

remote="https://x-access-token:${GITHUB_TOKEN}@github.com/${GITHUB_REPOSITORY}.git"

if ! git ls-remote --exit-code --heads "$remote" gh-pages >/dev/null 2>&1; then
  echo "No gh-pages branch; nothing to remove."
  exit 0
fi

work="$(mktemp -d)"
trap 'rm -rf "$work"' EXIT
git clone --quiet --depth 1 --branch gh-pages "$remote" "$work"
cd "$work"

removed=()
for pr in "$@"; do
  if [[ -d "preview/pr-${pr}" ]]; then
    rm -rf "preview/pr-${pr}"
    removed+=("#${pr}")
  else
    echo "No preview for PR #${pr}."
  fi
done

if [[ ${#removed[@]} -eq 0 ]]; then
  exit 0
fi

if [[ ${#removed[@]} -eq 1 ]]; then
  message="docs: drop preview for PR ${removed[0]}"
else
  message="docs: drop previews for PRs ${removed[*]}"
fi

git config user.name "github-actions[bot]"
git config user.email "github-actions[bot]@users.noreply.github.com"
git add --all
git commit --quiet --message "$message"

for attempt in 1 2 3; do
  if git push --quiet origin gh-pages; then
    echo "Removed ${#removed[@]} preview(s): ${removed[*]}"
    exit 0
  fi
  echo "Push rejected (attempt ${attempt}); rebasing onto the current branch."
  git fetch --quiet --depth 1 origin gh-pages
  git rebase --quiet FETCH_HEAD
done

echo "Could not remove previews ${removed[*]} after 3 attempts." >&2
exit 1
