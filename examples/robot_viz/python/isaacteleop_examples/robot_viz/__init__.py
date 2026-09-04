# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""A robot's digital twin rendered into an Isaac Teleop Televiz XR session.

Pure Python. The scene backend lives in `isaacteleop.viz.robot` and carries a MuJoCo of
its own, so this example neither compiles anything nor cares what `mujoco` the
environment happens to have.
"""
