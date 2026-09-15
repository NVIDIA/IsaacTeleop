#!/bin/bash
# SPDX-FileCopyrightText: Copyright (c) 2025-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
#
# Records one take of the G4 motion script, speaking the cues and labelling the result.
# Run it again for another take; nothing is ever overwritten.
#
#   ./record.sh [device]
#
#   ~/isaacteleop-captures/<device>/<date>/<time>-g4.mcap
#                                         /<time>-g4.labels.json
#                                         /<time>-g4.log
#                                         /<time>-g4.json      (what produced it)
#   ~/isaacteleop-captures/latest.mcap -> the newest take
#
# The recorder runs in the background and the prompter in the foreground. The two need
# no common clock: the labels are anchored to the clap in the recording's own frames,
# and make_labels.py re-derives every window from independent signals before it
# trusts that anchor.

set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO="$(cd "$HERE/../../.." && pwd)"
CAPTURES="$HOME/isaacteleop-captures"

DEVICE="${1:-pico4u}"
RECORDER_HEAD_START=6

cd "$REPO"

if [[ ! -x .venv-runtime/bin/python ]]; then
    echo "missing .venv-runtime; build the repo first" >&2
    exit 1
fi

SCRIPT_S=$(python3 -c "import sys; sys.path.insert(0,'$HERE'); \
import session; print(session.total_duration_s())")
DURATION=$(python3 -c "print(int($SCRIPT_S + 20))")

day="$CAPTURES/$DEVICE/$(date +%Y-%m-%d)"
mkdir -p "$day"
stem="$day/$(date +%H%M%S)-g4"

python3 - "$stem.json" "$DEVICE" "$DURATION" <<'PY'
import datetime, json, pathlib, subprocess, sys
path, device, duration = sys.argv[1:4]
def run(*args):
    try:
        return subprocess.run(args, capture_output=True, text=True,
                              check=True).stdout.strip()
    except Exception:
        return None
pathlib.Path(path).write_text(json.dumps({
    "recorded_at": datetime.datetime.now().astimezone().isoformat(),
    "device": device,
    "recording_duration_s": int(duration),
    "repo_commit": run("git", "rev-parse", "HEAD"),
    "host": run("hostname"),
}, indent=2) + "\n")
PY

echo "script ${SCRIPT_S}s, recording ${DURATION}s"
echo "take: $stem.mcap"
echo

.venv-runtime/bin/python -u examples/mcap_record_replay/python/record_full_body.py \
    "$DURATION" "$stem.mcap" >"$stem.log" 2>&1 &
recorder=$!

sleep "$RECORDER_HEAD_START"
if ! kill -0 "$recorder" 2>/dev/null; then
    echo "recorder exited during startup; see $stem.log" >&2
    tail -20 "$stem.log" >&2
    exit 1
fi

python3 "$HERE/prompter.py"
wait "$recorder"

echo
"$REPO/acceptance/full_body/checker/.venv/bin/python" \
    "$HERE/make_labels.py" "$stem.mcap" --write || true

ln -sfn "$stem.mcap" "$CAPTURES/latest.mcap"
echo
echo "run again for another take; this one is kept either way"
