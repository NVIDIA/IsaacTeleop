# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""The SO-101 scene the preview arm and the leader ghost are drawn from.

The three MJCF files are tracked package data; the 18 MB of upstream mesh and MJCF they
name is fetched, not vendored. :func:`ensure_so101_scene` assembles both halves into one
cache directory and returns the scene path.

Downloads are checksum-verified against a pinned commit: a raw.githubusercontent path is
not immutable in practice, and a substituted mesh renders as a broken arm rather than an
error. Everything lands flat, because MuJoCo drops an included file's own ``meshdir``; the
leader's servo is fetched under its own name so it cannot collide with the follower's copy.
"""

from __future__ import annotations

import hashlib
import os
import shutil
import urllib.request
from pathlib import Path

#: Bump this and the checksums together, or the download is refused.
SO_ARM_REPO = "TheRobotStudio/SO-ARM100"
SO_ARM_COMMIT = "fda892cba81032c46c40976a48c9ceadbf40a9ca"

#: ``(upstream path, destination name, sha256)``. The destination is per entry because
#: ``sts3215_03a_v1.stl`` is fetched twice -- the leader fragment names its copy
#: ``STS3215_03a.stl`` -- and a flat directory cannot alias the two.
#:
#: ``so101_new_calib.urdf`` is not drawn; it is on disk to check :mod:`.so101_ghost`'s
#: trigger hinge and travel against. ``joints_properties.xml`` is deliberately absent:
#: upstream inlines its ``<default>`` block, so the file is never read.
SO_ARM_ASSETS: tuple[tuple[str, str, str], ...] = (
    # The leader gripper ghost.
    (
        "STL/SO101/Individual/Wrist_Roll_SO101.stl",
        "Wrist_Roll_SO101.stl",
        "de3a65044dd4ae8bcb9659d8ca2b49598e3f5571edf89f45ad975e9776a7ffee",
    ),
    (
        "STL/SO101/Individual/Trigger_SO101.stl",
        "Trigger_SO101.stl",
        "48ecec3a3710cffdc0ae96d28547e49ddf4cbc93ccd915be7549f78e00ad2850",
    ),
    (
        "STL/SO101/Individual/Handle_SO101.stl",
        "Handle_SO101.stl",
        "fb8757bdff009c04c207481dd664813ccdac2ad989acea6057df780b52327281",
    ),
    (
        "Simulation/SO101/assets/sts3215_03a_v1.stl",
        "STS3215_03a.stl",
        "a37c871fb502483ab96c256baf457d36f2e97afc9205313d9c5ab275ef941cd0",
    ),
    (
        "Simulation/SO101/so101_new_calib.urdf",
        "so101_new_calib.urdf",
        "3a65d2d35e68a8d2f0c2cc176d19b884506543c93ba72980145b80abe276022c",
    ),
    (
        "LICENSE",
        "LICENSE",
        "c71d239df91726fc519c6eb72d318ec65820627232b2f796219e87dcf35d0ab4",
    ),
    # The follower arm.
    (
        "Simulation/SO101/so101_new_calib.xml",
        "so101_new_calib.xml",
        "d75253eb568e8a7214db9c631ab7bed4217f608a26f7276ebe9a7636cac82580",
    ),
    (
        "Simulation/SO101/assets/base_motor_holder_so101_v1.stl",
        "base_motor_holder_so101_v1.stl",
        "8cd2f241037ea377af1191fffe0dd9d9006beea6dcc48543660ed41647072424",
    ),
    (
        "Simulation/SO101/assets/base_so101_v2.stl",
        "base_so101_v2.stl",
        "bb12b7026575e1f70ccc7240051f9d943553bf34e5128537de6cd86fae33924d",
    ),
    (
        "Simulation/SO101/assets/motor_holder_so101_base_v1.stl",
        "motor_holder_so101_base_v1.stl",
        "31242ae6fb59d8b15c66617b88ad8e9bded62d57c35d11c0c43a70d2f4caa95b",
    ),
    (
        "Simulation/SO101/assets/motor_holder_so101_wrist_v1.stl",
        "motor_holder_so101_wrist_v1.stl",
        "887f92e6013cb64ea3a1ab8675e92da1e0beacfd5e001f972523540545e08011",
    ),
    (
        "Simulation/SO101/assets/moving_jaw_so101_v1.stl",
        "moving_jaw_so101_v1.stl",
        "785a9dded2f474bc1d869e0d3dae398a3dcd9c0c345640040472210d2861fa9d",
    ),
    (
        "Simulation/SO101/assets/rotation_pitch_so101_v1.stl",
        "rotation_pitch_so101_v1.stl",
        "9be900cc2a2bf718102841ef82ef8d2873842427648092c8ed2ca1e2ef4ffa34",
    ),
    (
        "Simulation/SO101/assets/sts3215_03a_no_horn_v1.stl",
        "sts3215_03a_no_horn_v1.stl",
        "75ef3781b752e4065891aea855e34dc161a38a549549cd0970cedd07eae6f887",
    ),
    (
        "Simulation/SO101/assets/sts3215_03a_v1.stl",
        "sts3215_03a_v1.stl",
        "a37c871fb502483ab96c256baf457d36f2e97afc9205313d9c5ab275ef941cd0",
    ),
    (
        "Simulation/SO101/assets/under_arm_so101_v1.stl",
        "under_arm_so101_v1.stl",
        "d01d1f2de365651dcad9d6669e94ff87ff7652b5bb2d10752a66a456a86dbc71",
    ),
    (
        "Simulation/SO101/assets/upper_arm_so101_v1.stl",
        "upper_arm_so101_v1.stl",
        "475056e03a17e71919b82fd88ab9a0b898ab50164f2a7943652a6b2941bb2d4f",
    ),
    (
        "Simulation/SO101/assets/waveshare_mounting_plate_so101_v2.stl",
        "waveshare_mounting_plate_so101_v2.stl",
        "e197e24005a07d01bbc06a8c42311664eaeda415bf859f68fa247884d0f1a6e9",
    ),
    (
        "Simulation/SO101/assets/wrist_roll_follower_so101_v1.stl",
        "wrist_roll_follower_so101_v1.stl",
        "4b17b410a12d64ec39554abc3e8054d8a97384b2dc4a8d95a5ecb2a93670f5f4",
    ),
    (
        "Simulation/SO101/assets/wrist_roll_pitch_so101_v2.stl",
        "wrist_roll_pitch_so101_v2.stl",
        "6c7ec5525b4d8b9e397a30ab4bb0037156a5d5f38a4adf2c7d943d6c56eda5ae",
    ),
)

#: The tracked wrappers. Re-copied on every call rather than gated on the completeness
#: marker, so editing one takes effect on the next run with no cache to clear.
SCENE_FILE = "scene.xml"
_WRAPPERS = (SCENE_FILE, "follower_arm.xml", "leader_gripper.xml")

#: Overrides where the assets are cached. Point it at a pre-populated directory on a host
#: with no route to GitHub.
CACHE_ENV_VAR = "ISAACTELEOP_SO101_ASSETS"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def ensure_so101_scene() -> Path:
    """Assemble the scene into the cache directory and return its path.

    The completeness marker gates the download only: the MJCF's existence is not a
    completeness signal, since an interrupted first run leaves the meshes it names missing.
    Re-running repairs a partial cache; delete the directory to force a re-download.

    Raises:
        RuntimeError: If a download's checksum does not match :data:`SO_ARM_ASSETS`.
        OSError: If the files cannot be fetched or written.
    """
    override = os.environ.get(CACHE_ENV_VAR, "").strip()
    if override:
        dest = Path(override)
    else:
        root = os.environ.get("XDG_CACHE_HOME", "").strip() or str(
            Path.home() / ".cache"
        )
        dest = Path(root) / "isaacteleop" / "so101-assets"
    dest.mkdir(parents=True, exist_ok=True)

    source = Path(__file__).parent / "assets"
    for wrapper in _WRAPPERS:
        shutil.copyfile(source / wrapper, dest / wrapper)

    marker = dest / ".fetch_complete"
    if not marker.exists():
        for remote, name, sha in SO_ARM_ASSETS:
            target = dest / name
            if target.is_file() and _sha256(target) == sha:
                continue
            url = f"https://raw.githubusercontent.com/{SO_ARM_REPO}/{SO_ARM_COMMIT}/{remote}"
            with urllib.request.urlopen(url, timeout=120) as response:  # nosec B310
                payload = response.read()
            if hashlib.sha256(payload).hexdigest() != sha:
                raise RuntimeError(
                    f"robot twin: checksum mismatch for {remote}. Upstream changed, or "
                    "SO_ARM_COMMIT and the hashes in SO_ARM_ASSETS disagree."
                )
            target.write_bytes(payload)
        marker.touch()

    # Absolute: on mujoco 3.11 a relative model path mis-composes an <include>d file's
    # path and fails naming a file that exists.
    return (dest / SCENE_FILE).resolve()
