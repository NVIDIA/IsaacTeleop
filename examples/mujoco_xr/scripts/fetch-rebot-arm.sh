#!/usr/bin/env bash
# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
#
# Fetches the reBot DevArm gripper assets `--robot=rebot` draws. Same contract as
# fetch-so-arm.sh beside it: nothing calls this at build time, the files land in
# package data, and the app fails at startup naming this script when they are
# absent.
#
# Fetch, then install:
#   uv pip install --reinstall-package isaacteleop-examples-mujoco-xr ./examples/mujoco_xr
#
# TODO: the download loop below is a copy of the one in fetch-so-arm.sh -- extract
# it into a shared helper once a third robot or asset set needs it.
set -euo pipefail

# The pin. Everything below is reproducible from this one line; bump it and the
# checksums together or the script refuses the download.
COMMIT="e56b035e335b2e8b8b333ed94860ac9e936b67ba"
REPO="Seeed-Projects/reBotArm_control_py"
SUBDIR="urdf/00-arm-rs_asm-v3"

DEST="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)/python/isaacteleop_examples/mujoco_xr/assets/rebot"

# upstream path <SPACE> local name <SPACE> sha256
#
# Seven meshes, which is the gripper_end link and both jaws -- the rest of the
# arm is not drawn. meshes/gripper_end.STL is deliberately absent: it is 4 MB
# that the URDF's gripper_end link does not reference.
#
# The URDF is not decoration: it is where rebot_gripper.xml's two jaw transforms
# and robots.py's travel come from, and having it on disk is what lets
# test_ghost.py check them against their source.
#
# README.md stands in for the LICENSE this repository does not have. Upstream
# declares MIT there ("This project is open source under the MIT License"); the
# hardware is Seeed-Projects/reBot-DevArm, CERN-OHL-W-2.0.
ASSETS=(
  "${SUBDIR}/meshes/pla7_green.STL pla7_green.STL 00b3c3d51f6f756ab96fc65a229610b952ce4a8be927e2ec404bacbcf43f4afc"
  "${SUBDIR}/meshes/cnc7.STL cnc7.STL 2d6088744c7d5195fc3f78d930dba9a9843ad208b2a6243fade1aaf17fecc782"
  "${SUBDIR}/meshes/motor_7.STL motor_7.STL 4e019eae9e44376b9d876eae995535bcca7761e4083a3ed0d8705d25cffa9dc1"
  "${SUBDIR}/meshes/pla_left.STL pla_left.STL 0e774ab0bf2975792982adf646465c7ed1ff35b9ed0ad9bf3fb14c9d7480ebef"
  "${SUBDIR}/meshes/cnc_left.STL cnc_left.STL 8f8ed951fad05dd5e3fec04f697864a64e394db9138d72fdfa62f8f047388aa6"
  "${SUBDIR}/meshes/pla_right.STL pla_right.STL 43556446abbbecd847bb09a4dc13d4ef2aa266a9ba904e5ac9ccff89a3c8280d"
  "${SUBDIR}/meshes/cnc_right.STL cnc_right.STL d7be82297465675b19b5651f3e25c5bab82d33a20bab2aa48ddffbbcf8c65072"
  "${SUBDIR}/urdf/00-arm-rs_asm-v3.urdf 00-arm-rs_asm-v3.urdf 2012b5aa3b58878109cb9e3c5deef919a87bd09a67d561662b2904a30dd4397e"
  "README.md README.md 52d59f12192379b5b4b2dadb712b8b0dd48431f3bb5ae1152ea7e05afd7055a0"
)

mkdir -p "$DEST"
echo "Fetching reBot DevArm assets at ${COMMIT:0:12} into ${DEST}"

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
