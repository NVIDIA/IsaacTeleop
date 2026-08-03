#!/bin/sh
# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
#
# Fetch the robot scenes this example ships from MuJoCo Menagerie (sparse
# checkout, pinned commit) into the example's own package data. Every Menagerie
# file is consumed BYTE-IDENTICAL -- this example never patches one.
#
# WHY A SEPARATE, EXPLICIT STEP and not a build hook: an isolated PEP-517 wheel
# build must not clone from GitHub, so nothing in CMakeLists.txt or
# pyproject.toml may reach the network. The app fails at startup naming this
# script instead (python/isaacteleop_examples/mujoco_xr/robot_spec.py's
# scene_missing()).
#
# WHERE IT UNPACKS, and this is the part that is not obvious.
#
# Menagerie's robot XMLs carry `<compiler meshdir="assets"/>`, and MuJoCo
# resolves the assets of an INCLUDED file against the included file's own
# directory -- measured on mujoco 3.11.0: a wrapper in a different directory
# that does `<include file="../menagerie/robotstudio_so101/so101.xml"/>` looks
# for the meshes at `<wrapper dir>/../menagerie/robotstudio_so101/<mesh>.stl`,
# i.e. with `meshdir` DROPPED, and fails to load. So the wrapper has to sit in
# the SAME directory as the robot XML it includes. Hence: this script unpacks
# each Menagerie robot directory on top of `assets/<scene id>/`, where the
# tracked, authored `ar_scene.xml` already lives, and that wrapper says
# `<include file="so101.xml"/>` with no path at all. It is the same staging the
# reference implementation does in CMake (MuJoCoXR's `mxr_stage_scene`), moved
# to the one directory that is also package data.
#
# CONSEQUENCE, stated because it surprises people: the fetched files become
# WHEEL PAYLOAD. `uv pip install ./examples/mujoco_xr` copies whatever is in
# `assets/` at that moment, so the order is FETCH FIRST, THEN INSTALL, and a
# wheel built after a fetch is ~55 MB rather than ~100 kB. Re-run the install
# after fetching or `--scene so101` will fail from site-packages while working
# from the source tree. The repository-root .gitignore keeps the payload
# untracked; scikit-build-core reads .gitignore relative to the PROJECT root
# (examples/mujoco_xr/), never the git root, so that rule does not also delete
# the payload from the wheel. Do not "tidy" it into examples/mujoco_xr/.gitignore
# -- that would silently ship a wheel with no robots in it.
#
# ADDING A ROBOT: append one row to SCENES below and one Scene row to
# robot_spec.py. Nothing else in this script changes -- the early exit, the
# sparse-checkout set and the copy loop are all derived from that one list, and
# tests/test_scenes.py asserts the two lists agree.

set -eu

# Overridable so a bump can be tried without editing the file, but the DEFAULT
# is the pin: an unset MENAGERIE_PIN must be reproducible, not "whatever main
# is today".
PIN=${MENAGERIE_PIN:-71f066ad0be9cd271f7ed58c030243ef157af9f4}
REPO=${MENAGERIE_REPO:-https://github.com/google-deepmind/mujoco_menagerie.git}

ROOT=$(cd "$(dirname "$0")/.." && pwd)
ASSETS="$ROOT/python/isaacteleop_examples/mujoco_xr/assets"

# <scene id>:<Menagerie directory>:<robot XML>. The two spellings are NOT the
# same and never will be: Menagerie names directories after the vendor, this
# example names scenes after the arm. robot_spec.py's Scene rows carry the same
# three fields and tests/test_scenes.py cross-checks them against this line.
SCENES="franka:franka_emika_panda:panda.xml so101:robotstudio_so101:so101.xml"

# A per-scene stamp, so a PIN BUMP RE-FETCHES instead of reporting "already
# fetched" forever. The reference implementation tested only for the robot XML
# and had exactly that bug in the other direction (a checkout made before a
# second robot was added never widened).
stamp_of() { echo "$ASSETS/$1/.menagerie-pin"; }

missing=""
for scene in $SCENES; do
    id=${scene%%:*}
    rest=${scene#*:}
    xml=${rest#*:}
    stamp=$(stamp_of "$id")
    if [ ! -f "$ASSETS/$id/$xml" ] || [ ! -f "$stamp" ] ||
        [ "$(cat "$stamp")" != "$PIN" ]; then
        missing="$missing $id"
    fi
done

if [ -z "$missing" ]; then
    echo "already fetched at $PIN:"
    for scene in $SCENES; do
        echo "  $ASSETS/${scene%%:*}"
    done
    exit 0
fi

echo "fetching$missing at $PIN"

# ONE clone for the whole run, and then EVERY scene is re-copied, not just the
# missing ones: a half-updated tree with two robots at two different pins is not
# a state worth being able to reach.
tmp=$(mktemp -d)
# shellcheck disable=SC2064  # $tmp must expand now, not at trap time.
trap "rm -rf '$tmp'" EXIT INT TERM

dirs=""
for scene in $SCENES; do
    rest=${scene#*:}
    dirs="$dirs ${rest%%:*}"
done

git clone --filter=blob:none --no-checkout "$REPO" "$tmp/menagerie"
# Unquoted on purpose: $dirs is a word list, one sparse-checkout path each.
# shellcheck disable=SC2086
git -C "$tmp/menagerie" sparse-checkout set $dirs
git -C "$tmp/menagerie" checkout "$PIN"

for scene in $SCENES; do
    id=${scene%%:*}
    rest=${scene#*:}
    dir=${rest%%:*}
    xml=${rest#*:}
    dest="$ASSETS/$id"

    if [ ! -f "$dest/ar_scene.xml" ]; then
        echo "error: $dest/ar_scene.xml is missing -- that file is TRACKED and" >&2
        echo "       authored here; this script only adds Menagerie beside it." >&2
        exit 1
    fi

    # Nothing is deleted first, deliberately: `ar_scene.xml` is a tracked file
    # living in this same directory, and a blanket `rm -rf "$dest"` that failed
    # halfway would take it with it. Menagerie ships no `ar_scene.xml`, so this
    # copy can never overwrite it. A file left behind by an older pin is
    # inert -- the loader only reads what the robot XML names.
    cp -R "$tmp/menagerie/$dir/." "$dest/"
    echo "$PIN" >"$(stamp_of "$id")"

    meshes=$(ls "$dest/assets" | wc -l)
    echo "fetched: $dest <- $dir ($xml, $meshes mesh files)"
done

echo
echo "Now REINSTALL the wheel so these files reach site-packages:"
echo "  uv pip install ./examples/mujoco_xr --reinstall-package isaacteleop-examples-mujoco-xr"
