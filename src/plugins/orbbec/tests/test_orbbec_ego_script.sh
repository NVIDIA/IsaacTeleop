#!/usr/bin/env bash
# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

set -euo pipefail

SCRIPT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)/orbbec_ego.sh"
TMPDIR_TEST="$(mktemp -d)"
trap 'rm -rf "$TMPDIR_TEST"' EXIT

expect_failure() {
    if "$@" >/dev/null 2>&1; then
        echo "Expected command to fail: $*" >&2
        exit 1
    fi
}

"$SCRIPT" --help >/dev/null
expect_failure "$SCRIPT" doctor --sdk-root "$TMPDIR_TEST/missing-sdk"
expect_failure "$SCRIPT" build --sdk-root "$TMPDIR_TEST/missing-sdk" --preset invalid
expect_failure "$SCRIPT" record --duration 0
expect_failure "$SCRIPT" record --format invalid

MOCK_PLUGIN="$TMPDIR_TEST/mock_plugin"
MOCK_ARGS="$TMPDIR_TEST/plugin_args"
cat > "$MOCK_PLUGIN" <<'EOF'
#!/usr/bin/env bash
if [[ "$1" == "--list-capabilities" ]]; then
    cat <<'CAPABILITIES'
Sensor Accel
Sensor Gyro
Sensor LeftColor
Sensor RightColor
Sensor Audio
CAPABILITIES
    exit 0
fi
printf '%s\n' "$@" > "$MOCK_ARGS"
exit 7
EOF
chmod +x "$MOCK_PLUGIN"

export MOCK_ARGS
RUN="$TMPDIR_TEST/recording"
expect_failure "$SCRIPT" record --plugin "$MOCK_PLUGIN" --duration 1 --output "$RUN" -- --bitrate=8
grep -Fx -- "--enable-imu" "$MOCK_ARGS" >/dev/null
grep -Fx -- "--audio-output=$RUN/Audio.wav" "$MOCK_ARGS" >/dev/null
grep -Fx -- "--mcap-filename=$RUN/metadata.mcap" "$MOCK_ARGS" >/dev/null
grep -Fx -- "--bitrate=8" "$MOCK_ARGS" >/dev/null
test -f "$RUN/capabilities.txt"
test -f "$RUN/logs/capture.log"

RUN_EMBEDDED="$TMPDIR_TEST/embedded"
expect_failure "$SCRIPT" record --plugin "$MOCK_PLUGIN" --duration 1 --output "$RUN_EMBEDDED" --mcap-media embedded
grep -Fx -- "--enable-audio" "$MOCK_ARGS" >/dev/null
if grep -q '^--audio-output=' "$MOCK_ARGS"; then
    echo "Embedded capture must not request a WAV sidecar by default" >&2
    exit 1
fi
