#!/usr/bin/env bash
# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
#
# Builds the fixture set into fixtures/ and reads it back. Run it after a fresh clone,
# and again after changing a generator: the .mcap files are derived and are not in git.
#
# There is no setup step and no venv here. The checker's setup_env.sh pins flatc, emits
# the bindings and installs the two packages this needs, so running a second copy of
# that would be a second flatc version to keep in step with the repo golden.
set -euo pipefail
cd "$(dirname "$0")"
CHECKER="$(cd ../checker && pwd)"

if [[ ! -x "$CHECKER/.venv/bin/python" ]]; then
  echo "missing $CHECKER/.venv; run $CHECKER/setup_env.sh first" >&2
  exit 1
fi
PY="$CHECKER/.venv/bin/python"

"$PY" generate_fixtures.py
"$PY" verify_fixtures.py
"$PY" g4_verify.py

# The index is committed and the fixtures are not, so a generator change that moves a
# byte shows up here as a dirty index rather than as a checker test failing later.
if ! git diff --quiet -- fixtures_index.json; then
  echo
  echo "fixtures_index.json changed -- review and commit it, or the oracle no longer" >&2
  echo "describes what this generator produces." >&2
  exit 1
fi
