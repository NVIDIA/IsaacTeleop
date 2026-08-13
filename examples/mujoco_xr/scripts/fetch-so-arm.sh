#!/usr/bin/env bash
# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
#
# Fetches the SO-101 leader-gripper assets, rather than vendoring 2.3 MB of
# binary STL that Git LFS made every clone pay for.
#
# Nothing calls this at build time: an isolated PEP-517 wheel build must not
# reach the network, so it is an explicit step and the app names it at startup.
# The files are package data, so REINSTALL afterwards -- skip that and the ghost
# works from the source tree and fails from the wheel.
set -euo pipefail

# The pin. Bump it and the checksums together or the download is refused.
COMMIT="fda892cba81032c46c40976a48c9ceadbf40a9ca"
REPO="TheRobotStudio/SO-ARM100"

DEST="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)/python/isaacteleop_examples/mujoco_xr/assets/leader"

# upstream path <SPACE> local name <SPACE> sha256
#
# The URDF is where app.py's trigger hinge comes from, and having it on disk is
# what lets test_ghost.py check those constants against their source.
ASSETS=(
  "STL/SO101/Individual/Wrist_Roll_SO101.stl Wrist_Roll_SO101.stl de3a65044dd4ae8bcb9659d8ca2b49598e3f5571edf89f45ad975e9776a7ffee"
  "STL/SO101/Individual/Trigger_SO101.stl Trigger_SO101.stl 48ecec3a3710cffdc0ae96d28547e49ddf4cbc93ccd915be7549f78e00ad2850"
  "STL/SO101/Individual/Handle_SO101.stl Handle_SO101.stl fb8757bdff009c04c207481dd664813ccdac2ad989acea6057df780b52327281"
  "Simulation/SO101/assets/sts3215_03a_v1.stl STS3215_03a.stl a37c871fb502483ab96c256baf457d36f2e97afc9205313d9c5ab275ef941cd0"
  "Simulation/SO101/so101_new_calib.urdf so101_new_calib.urdf 3a65d2d35e68a8d2f0c2cc176d19b884506543c93ba72980145b80abe276022c"
  "LICENSE LICENSE c71d239df91726fc519c6eb72d318ec65820627232b2f796219e87dcf35d0ab4"
)

mkdir -p "$DEST"
echo "Fetching SO-ARM100 assets at ${COMMIT:0:12} into ${DEST}"

for entry in "${ASSETS[@]}"; do
  read -r remote local sha <<<"$entry"
  target="${DEST}/${local}"
  if [[ -f "$target" ]] && echo "${sha}  ${target}" | sha256sum --check --status; then
    echo "  ok       ${local}"
    continue
  fi
  url="https://raw.githubusercontent.com/${REPO}/${COMMIT}/${remote}"
  echo "  fetching ${local}"
  curl -fsSL "$url" -o "${target}.part"
  # A raw.githubusercontent path is not immutable in practice, and a silently
  # substituted mesh renders as a broken gripper rather than an error.
  if ! echo "${sha}  ${target}.part" | sha256sum --check --status; then
    rm -f "${target}.part"
    echo "ERROR: checksum mismatch for ${remote}." >&2
    echo "       Upstream changed, or COMMIT and the hashes above disagree." >&2
    exit 1
  fi
  mv "${target}.part" "$target"
done

echo
echo "Done. These are package data, so install before running:"
echo "  uv pip install --reinstall-package isaacteleop-examples-mujoco-xr ./examples/mujoco_xr"
