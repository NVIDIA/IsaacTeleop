# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""The acceptance panel: what the text report cannot show, which is where and when.

``track``, ``status`` and ``render`` are pure Python over the checker's own types.
``app`` is the only module that imports viser, and viser is an optional extra — see
``tests/test_panel_boundary.py``, which holds that line mechanically.
"""
