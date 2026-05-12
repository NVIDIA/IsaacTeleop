<!--
SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
SPDX-License-Identifier: Apache-2.0
-->

# Teleop ROS 2 Agent Notes

## Docker Validation

- When creating temporary Docker images for `examples/teleop_ros2` validation, remove them before finishing the task unless the user explicitly asks to keep them.

## Python Node Layout

- In `python/teleop_ros2_node.py`, preserve the existing grouped/sorted organization for global non-member helpers and for `TeleopRos2Node` member functions. When adding a helper or method, place it in the matching existing group rather than near the first call site.
