# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Stage the public V2D files required by Isaac Teleop."""

from __future__ import annotations

import argparse
import shutil
import xml.etree.ElementTree as ET
from pathlib import Path

_RETARGET_FILES = (
    "__init__.py",
    "hand_kinematics.py",
    "params.py",
    "pinocchio_viser_visualizer.py",
    "utils.py",
)
_SIDES = ("left", "right")


def _copy_file(source: Path, destination: Path) -> None:
    if not source.is_file():
        raise FileNotFoundError(f"required V2D file is missing: {source}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, destination)


def _write_mesh_free_mjcf(source: Path, destination: Path) -> None:
    tree = ET.parse(source)
    root = tree.getroot()
    expected_joints = {
        element.attrib["name"]
        for element in root.iter("joint")
        if "name" in element.attrib
    }
    expected_sites = {
        element.attrib["name"]
        for element in root.iter("site")
        if "name" in element.attrib
    }

    compiler = root.find("compiler")
    if compiler is not None:
        compiler.attrib.pop("meshdir", None)

    asset = root.find("asset")
    if asset is not None:
        root.remove(asset)

    removed_geometries = 0
    for parent in root.iter():
        for child in list(parent):
            if child.tag == "geom" and (
                child.attrib.get("type") == "mesh" or "mesh" in child.attrib
            ):
                parent.remove(child)
                removed_geometries += 1

    if removed_geometries == 0:
        raise ValueError(f"expected mesh geometries in {source}")

    remaining_meshes = [
        element
        for element in root.iter()
        if element.tag == "mesh"
        or (
            element.tag == "geom"
            and (element.attrib.get("type") == "mesh" or "mesh" in element.attrib)
        )
    ]
    if remaining_meshes:
        raise ValueError(f"mesh references remain in generated MJCF: {source}")
    actual_joints = {
        element.attrib["name"]
        for element in root.iter("joint")
        if "name" in element.attrib
    }
    actual_sites = {
        element.attrib["name"]
        for element in root.iter("site")
        if "name" in element.attrib
    }
    if actual_joints != expected_joints or actual_sites != expected_sites:
        raise ValueError(f"joint or IK target site changed while stripping {source}")

    ET.indent(tree, space="  ")
    destination.parent.mkdir(parents=True, exist_ok=True)
    tree.write(destination, encoding="utf-8", xml_declaration=True)


def stage(source_root: Path, output_root: Path) -> None:
    package_source = (
        source_root
        / "robotic_grounding"
        / "source"
        / "robotic_grounding"
        / "robotic_grounding"
    )
    retarget_source = package_source / "retarget"
    sharpa_source = package_source / "assets" / "xmls" / "sharpawave"

    shutil.rmtree(output_root, ignore_errors=True)
    output_root.mkdir(parents=True)

    _copy_file(package_source / "__init__.py", output_root / "__init__.py")
    for filename in _RETARGET_FILES:
        _copy_file(
            retarget_source / filename,
            output_root / "retarget" / filename,
        )

    assets_output = output_root / "assets" / "xmls" / "sharpawave"
    for filename in ("LICENSE", "NOTICE", "README.md"):
        _copy_file(sharpa_source / filename, assets_output / filename)
    _copy_file(source_root / "LICENSE", output_root / "V2D_LICENSE")

    for side in _SIDES:
        _copy_file(
            sharpa_source / f"{side}_sharpawave.xml",
            assets_output / f"{side}_sharpawave.xml",
        )
        _write_mesh_free_mjcf(
            sharpa_source / f"{side}_sharpawave.xml",
            assets_output / f"{side}_sharpawave_nomesh.xml",
        )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    args = parser.parse_args()
    stage(args.source_root.resolve(), args.output_root.resolve())


if __name__ == "__main__":
    main()
