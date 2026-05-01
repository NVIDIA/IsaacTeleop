#!/usr/bin/env python3
# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Remove robotic_grounding/* entries from one or more wheel files.

The Teleop wheel build bundles `robotic_grounding/` from
`deps/v2d/src/robotic_grounding/` when V2D access was available at build
time -- giving local builds and internal CI a "Just Works" `[grounding]`
extra. The bundled wheel is, however, not safe to upload as a public
GitHub Actions artifact (V2D source is private). This script rewrites
the wheel(s) in place, dropping every `robotic_grounding/...` entry from
the zip while leaving everything else intact.

The RECORD file inside the .dist-info dir is regenerated to match the
remaining contents so `pip install` / `wheel inspect` stay consistent.

Usage:
    python scripts/strip_robotic_grounding_from_wheel.py PATH [PATH ...]
"""

import argparse
import base64
import hashlib
import shutil
import sys
import tempfile
import zipfile
from pathlib import Path


def _record_line(arcname: str, data: bytes) -> str:
    digest = hashlib.sha256(data).digest()
    b64 = base64.urlsafe_b64encode(digest).rstrip(b"=").decode()
    return f"{arcname},sha256={b64},{len(data)}\n"


def strip_wheel(wheel_path: Path) -> bool:
    """Return True if the wheel was modified, False otherwise."""
    with zipfile.ZipFile(wheel_path) as zin:
        names = zin.namelist()

    targets = [n for n in names if n.startswith("robotic_grounding/")]
    if not targets:
        print(f"  {wheel_path.name}: no robotic_grounding/ entries; leaving as-is")
        return False

    print(f"  {wheel_path.name}: removing {len(targets)} robotic_grounding/ entries")

    record_arcname: str | None = None
    for n in names:
        if n.endswith(".dist-info/RECORD"):
            record_arcname = n
            break

    with tempfile.TemporaryDirectory() as td:
        out_path = Path(td) / "out.whl"
        kept_records: list[str] = []
        with (
            zipfile.ZipFile(wheel_path) as zin,
            zipfile.ZipFile(out_path, "w", zipfile.ZIP_DEFLATED) as zout,
        ):
            for item in zin.infolist():
                if item.filename.startswith("robotic_grounding/"):
                    continue
                if item.filename == record_arcname:
                    # Defer; we rewrite RECORD last to reflect the new contents.
                    continue
                data = zin.read(item.filename)
                zout.writestr(item, data)
                kept_records.append(_record_line(item.filename, data))

            if record_arcname is not None:
                # RECORD itself has no hash/size column for its own row.
                kept_records.append(f"{record_arcname},,\n")
                zout.writestr(record_arcname, "".join(kept_records))

        shutil.move(out_path, wheel_path)

    return True


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("wheels", nargs="+", help="Wheel files to strip in place.")
    args = parser.parse_args(argv)

    any_modified = False
    for w in args.wheels:
        path = Path(w)
        if not path.is_file():
            print(f"  {path}: not a file, skipping", file=sys.stderr)
            continue
        if strip_wheel(path):
            any_modified = True

    if any_modified:
        print("done.")
    else:
        print("no wheels were modified.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
