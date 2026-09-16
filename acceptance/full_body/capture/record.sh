#!/bin/bash
# SPDX-FileCopyrightText: Copyright (c) 2025-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
#
# Records one take of the G4 motion script. Run it again for another take; nothing is
# ever overwritten.
#
#   ./record.sh [device]
#
#   ~/isaacteleop-captures/<device>/<date>/<time>-g4.mcap
#                                         /<time>-g4.labels.json
#                                         /<time>-g4.log
#                                         /<time>-g4.json      (what produced it)
#
# This only names the take and records what produced it. Everything else -- the panel,
# the cues, the windows and the sidecar -- is capture_panel.py in one process, because
# the take is paced by the performer and its length is not known in advance.

set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CAPTURES="$HOME/isaacteleop-captures"

DEVICE="${1:-pico4u}"
shift || true

if [[ ! -x "$HERE/.venv/bin/python" ]]; then
    echo "missing $HERE/.venv; run $HERE/setup_env.sh" >&2
    exit 1
fi

day="$CAPTURES/$DEVICE/$(date +%Y-%m-%d)"
mkdir -p "$day"
stem="$day/$(date +%H%M%S)-g4"

# -C, because record.sh is normally invoked by path from somewhere else entirely and a
# bare `git rev-parse` would then describe the caller's directory or nothing at all.
python3 - "$stem.json" "$DEVICE" "$HERE" <<'PY'
import datetime, json, pathlib, subprocess, sys
path, device, here = sys.argv[1:4]
def run(*args):
    try:
        return subprocess.run(args, capture_output=True, text=True,
                              check=True).stdout.strip()
    except Exception:
        return None
pathlib.Path(path).write_text(json.dumps({
    "recorded_at": datetime.datetime.now().astimezone().isoformat(),
    "device": device,
    "repo_commit": run("git", "-C", here, "rev-parse", "HEAD"),
    "host": run("hostname"),
}, indent=2) + "\n")
PY

echo "take: $stem.mcap"
echo

"$HERE/.venv/bin/python" -u "$HERE/capture_panel.py" "$stem.mcap" "$@" \
    2>&1 | tee "$stem.log"

echo
echo "run again for another take; this one is kept either way"
