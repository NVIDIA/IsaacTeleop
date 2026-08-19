#!/usr/bin/env bash
# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
#
# Fetches the SO-101 assets this example draws -- the leader gripper the ghost
# is made of, and the follower arm -- rather than vendoring 18 MB of binary STL
# that Git LFS made every clone pay for.
#
# Nothing calls this at build time: an isolated PEP-517 wheel build must not
# reach the network, so it is an explicit step and the app names it at startup.
# The files are package data, so REINSTALL afterwards -- skip that and the ghost
# works from the source tree and fails from the wheel.
set -euo pipefail

# The pin. Bump it and the checksums together or the download is refused.
COMMIT="fda892cba81032c46c40976a48c9ceadbf40a9ca"
REPO="TheRobotStudio/SO-ARM100"

DEST="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)/python/isaacteleop_examples/mujoco_xr/assets"

# upstream path <SPACE> destination relative to assets/ <SPACE> sha256
#
# The destination is per entry, not per script: the two tools are separate MJCF
# fragments in separate directories. Both land FLAT beside their fragment --
# MuJoCo drops an included file's own `meshdir`, so meshes under a further
# assets/ subdirectory fail to open.
#
# The URDF is where app.py's trigger hinge comes from, and having it on disk is
# what lets test_ghost.py check those constants against their source.
#
# sts3215_03a_v1.stl is fetched TWICE, once per tool, because each fragment
# resolves its meshes against its own directory. A symlink or a `../leader/`
# path would tie the follower fragment's layout to the leader's.
#
# joints_properties.xml is deliberately absent: upstream inlines its `<default>`
# block into so101_new_calib.xml rather than <include>ing it, so the file is
# never read.
ASSETS=(
  "STL/SO101/Individual/Wrist_Roll_SO101.stl leader/Wrist_Roll_SO101.stl de3a65044dd4ae8bcb9659d8ca2b49598e3f5571edf89f45ad975e9776a7ffee"
  "STL/SO101/Individual/Trigger_SO101.stl leader/Trigger_SO101.stl 48ecec3a3710cffdc0ae96d28547e49ddf4cbc93ccd915be7549f78e00ad2850"
  "STL/SO101/Individual/Handle_SO101.stl leader/Handle_SO101.stl fb8757bdff009c04c207481dd664813ccdac2ad989acea6057df780b52327281"
  "Simulation/SO101/assets/sts3215_03a_v1.stl leader/STS3215_03a.stl a37c871fb502483ab96c256baf457d36f2e97afc9205313d9c5ab275ef941cd0"
  "Simulation/SO101/so101_new_calib.urdf leader/so101_new_calib.urdf 3a65d2d35e68a8d2f0c2cc176d19b884506543c93ba72980145b80abe276022c"
  "LICENSE leader/LICENSE c71d239df91726fc519c6eb72d318ec65820627232b2f796219e87dcf35d0ab4"

  "Simulation/SO101/so101_new_calib.xml follower/so101_new_calib.xml d75253eb568e8a7214db9c631ab7bed4217f608a26f7276ebe9a7636cac82580"
  "Simulation/SO101/assets/base_motor_holder_so101_v1.stl follower/base_motor_holder_so101_v1.stl 8cd2f241037ea377af1191fffe0dd9d9006beea6dcc48543660ed41647072424"
  "Simulation/SO101/assets/base_so101_v2.stl follower/base_so101_v2.stl bb12b7026575e1f70ccc7240051f9d943553bf34e5128537de6cd86fae33924d"
  "Simulation/SO101/assets/motor_holder_so101_base_v1.stl follower/motor_holder_so101_base_v1.stl 31242ae6fb59d8b15c66617b88ad8e9bded62d57c35d11c0c43a70d2f4caa95b"
  "Simulation/SO101/assets/motor_holder_so101_wrist_v1.stl follower/motor_holder_so101_wrist_v1.stl 887f92e6013cb64ea3a1ab8675e92da1e0beacfd5e001f972523540545e08011"
  "Simulation/SO101/assets/moving_jaw_so101_v1.stl follower/moving_jaw_so101_v1.stl 785a9dded2f474bc1d869e0d3dae398a3dcd9c0c345640040472210d2861fa9d"
  "Simulation/SO101/assets/rotation_pitch_so101_v1.stl follower/rotation_pitch_so101_v1.stl 9be900cc2a2bf718102841ef82ef8d2873842427648092c8ed2ca1e2ef4ffa34"
  "Simulation/SO101/assets/sts3215_03a_no_horn_v1.stl follower/sts3215_03a_no_horn_v1.stl 75ef3781b752e4065891aea855e34dc161a38a549549cd0970cedd07eae6f887"
  "Simulation/SO101/assets/sts3215_03a_v1.stl follower/sts3215_03a_v1.stl a37c871fb502483ab96c256baf457d36f2e97afc9205313d9c5ab275ef941cd0"
  "Simulation/SO101/assets/under_arm_so101_v1.stl follower/under_arm_so101_v1.stl d01d1f2de365651dcad9d6669e94ff87ff7652b5bb2d10752a66a456a86dbc71"
  "Simulation/SO101/assets/upper_arm_so101_v1.stl follower/upper_arm_so101_v1.stl 475056e03a17e71919b82fd88ab9a0b898ab50164f2a7943652a6b2941bb2d4f"
  "Simulation/SO101/assets/waveshare_mounting_plate_so101_v2.stl follower/waveshare_mounting_plate_so101_v2.stl e197e24005a07d01bbc06a8c42311664eaeda415bf859f68fa247884d0f1a6e9"
  "Simulation/SO101/assets/wrist_roll_follower_so101_v1.stl follower/wrist_roll_follower_so101_v1.stl 4b17b410a12d64ec39554abc3e8054d8a97384b2dc4a8d95a5ecb2a93670f5f4"
  "Simulation/SO101/assets/wrist_roll_pitch_so101_v2.stl follower/wrist_roll_pitch_so101_v2.stl 6c7ec5525b4d8b9e397a30ab4bb0037156a5d5f38a4adf2c7d943d6c56eda5ae"
)

echo "Fetching SO-ARM100 assets at ${COMMIT:0:12} into ${DEST}"

for entry in "${ASSETS[@]}"; do
  read -r remote local sha <<<"$entry"
  target="${DEST}/${local}"
  mkdir -p "$(dirname "$target")"
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
