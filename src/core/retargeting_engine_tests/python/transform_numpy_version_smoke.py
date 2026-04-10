# SPDX-FileCopyrightText: Copyright (c) 2025-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""
Smoke entrypoint for ``test_transform_numpy_versions``.

Run under ``uv run --no-project --with 'numpy==…'`` so the interpreter sees a
pinned NumPy while ``PYTHONPATH`` still points at the built ``isaacteleop``
package. Invoked as:

    python transform_numpy_version_smoke.py <1.23|2>
"""

from __future__ import annotations

import sys


def main() -> None:
    if len(sys.argv) != 2 or sys.argv[1] not in ("1.23", "2"):
        raise SystemExit("usage: transform_numpy_version_smoke.py <1.23|2>")

    key = sys.argv[1]

    import numpy as np

    if key == "1.23":
        if not np.__version__.startswith("1.23"):
            raise AssertionError(f"expected NumPy 1.23.x, got {np.__version__}")
        if not hasattr(np, "from_dlpack"):
            raise AssertionError("expected numpy.from_dlpack (NumPy 1.23+)")
    else:
        major = int(np.__version__.split(".")[0])
        if major < 2:
            raise AssertionError(f"expected NumPy 2.x+, got {np.__version__}")

    from isaacteleop.retargeting_engine.interface import TensorGroup
    from isaacteleop.retargeting_engine.tensor_types import (
        HeadPose,
        HeadPoseIndex,
        TransformMatrix,
    )
    from isaacteleop.retargeting_engine.utilities import HeadTransform

    head_in = TensorGroup(HeadPose())
    head_in[HeadPoseIndex.POSITION] = np.array([1.0, 2.0, 3.0], dtype=np.float32)
    head_in[HeadPoseIndex.ORIENTATION] = np.array(
        [0.0, 0.0, 0.0, 1.0], dtype=np.float32
    )
    head_in[HeadPoseIndex.IS_VALID] = True

    xform_in = TensorGroup(TransformMatrix())
    xform_in[0] = np.eye(4, dtype=np.float32)

    node = HeadTransform("numpy_smoke_head")
    result = node({"head": head_in, "transform": xform_in})
    out = result["head"]
    pos = out[HeadPoseIndex.POSITION]
    if not np.allclose(pos, [1.0, 2.0, 3.0], rtol=0, atol=1e-4):
        raise AssertionError(f"unexpected position {pos!r}")


if __name__ == "__main__":
    main()
