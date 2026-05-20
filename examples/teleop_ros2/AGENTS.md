<!--
SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
SPDX-License-Identifier: Apache-2.0
-->

# Teleop ROS 2 Agent Notes

## Docker Validation

- When creating temporary Docker images for `examples/teleop_ros2` validation, remove them before finishing the task unless the user explicitly asks to keep them.

## Python Node Layout

- In `python/teleop_ros2_node.py`, preserve the existing grouped/sorted organization for global non-member helpers and `TeleopRos2Node` member functions: scan the surrounding order before inserting, and do not place helpers near call sites when the existing section is sorted.
- In Python integration test verifier code, do not use bare `assert` for runtime validation; Python optimization can disable it, so raise explicit exceptions from validators.
