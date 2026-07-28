# SPDX-FileCopyrightText: Copyright (c) 2026 Wuji Technology. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Cross-check the two copies of the Wuji MediaPipe<->OpenXR joint mapping.

Both tables hold the same 21 entries — entry i is the OpenXR joint that
carries MediaPipe landmark i — but they drive opposite conversions: the C++
plugin scatters MediaPipe -> OpenXR (kMpToXr in wuji_glove_plugin.cpp) while
the Python retargeter gathers OpenXR -> MediaPipe (OPENXR_TO_MEDIAPIPE_INDICES
in wuji_hand_retargeter.py). They must stay identical entry for entry, or
joints get silently permuted at runtime.

Both tables are parsed from source so this test needs no wuji_sdk and runs
in the plain dev environment — unlike test_wuji_hand_retargeter.py, which
is gated on the wuji extra.
"""

import re
from pathlib import Path

import pytest

from isaacteleop.retargeting_engine.tensor_types import HandJointIndex

_SRC = Path(__file__).resolve().parents[3]
_PLUGIN_CPP = _SRC / "plugins" / "wuji_glove" / "wuji_glove_plugin.cpp"
_RETARGETER_PY = _SRC / "retargeters" / "wuji_hand_retargeter.py"


def _parse_cpp_table() -> list:
    text = _PLUGIN_CPP.read_text(encoding="utf-8")
    match = re.search(r"kMpToXr\[21\]\s*=\s*\{(.*?)\};", text, re.DOTALL)
    assert match, "kMpToXr table not found in wuji_glove_plugin.cpp"
    return re.findall(r"XR_HAND_JOINT_(\w+?)_EXT", match.group(1))


def _parse_python_table() -> list:
    text = _RETARGETER_PY.read_text(encoding="utf-8")
    match = re.search(
        r"OPENXR_TO_MEDIAPIPE_INDICES: list\[int\] = \[(.*?)\]", text, re.DOTALL
    )
    assert match, "OPENXR_TO_MEDIAPIPE_INDICES not found in wuji_hand_retargeter.py"
    return re.findall(r"HandJointIndex\.(\w+)", match.group(1))


def test_mapping_tables_agree():
    if not _PLUGIN_CPP.exists() or not _RETARGETER_PY.exists():
        pytest.skip("repo source tree not available")

    cpp_names = _parse_cpp_table()
    py_names = _parse_python_table()
    assert len(cpp_names) == len(py_names) == 21

    # Resolving through HandJointIndex also rejects typo'd joint names.
    cpp_indices = [int(getattr(HandJointIndex, name)) for name in cpp_names]
    py_indices = [int(getattr(HandJointIndex, name)) for name in py_names]
    assert cpp_indices == py_indices, (
        "kMpToXr (C++) and OPENXR_TO_MEDIAPIPE_INDICES (Python) disagree — "
        "the two copies of the MediaPipe<->OpenXR joint mapping have drifted"
    )
