#!/bin/bash
# SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
#
# Download sample video data for testing the camera streamer without physical cameras.
#
# Usage:
#   ./test/setup_test_data.sh
#
# Then run:
#   ./camera_streamer.sh run -- --source local --config test/video_file.yaml --mode monitor

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
DATA_DIR="$SCRIPT_DIR/data"
STAMP_FILE="$DATA_DIR/.racerx_stamp"

RACERX_URL="https://edge.urm.nvidia.com/artifactory/sw-holoscan-thirdparty-generic-local/data/racerx/racerx_20231009.zip"
RACERX_MD5="b67492afea29610105995c4c27bd5a05"

if [[ -f "$STAMP_FILE" ]]; then
    echo "Test data already present at $DATA_DIR"
    exit 0
fi

echo "Downloading racerx sample data..."
mkdir -p "$DATA_DIR"

ZIP_FILE="$(mktemp /tmp/racerx_XXXXXX.zip)"
trap 'rm -f "$ZIP_FILE"' EXIT

curl -fSL --progress-bar -o "$ZIP_FILE" "$RACERX_URL"

# Verify checksum
ACTUAL_MD5="$(md5sum "$ZIP_FILE" | cut -d' ' -f1)"
if [[ "$ACTUAL_MD5" != "$RACERX_MD5" ]]; then
    echo "ERROR: MD5 mismatch (expected $RACERX_MD5, got $ACTUAL_MD5)" >&2
    exit 1
fi

# Extract (zip contents are flat — files land directly in DATA_DIR)
unzip -qo "$ZIP_FILE" -d "$DATA_DIR"

touch "$STAMP_FILE"
echo "Done: $DATA_DIR"
ls -lh "$DATA_DIR"/racerx.gxf_*
