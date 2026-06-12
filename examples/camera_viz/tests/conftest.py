# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

# Tests live in examples/camera_viz/tests/ but import from
# examples/camera_viz/ (the example's pipeline / sources modules).
# Prepend the parent dir so those imports resolve against the in-tree
# source rather than any installed copy.

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
