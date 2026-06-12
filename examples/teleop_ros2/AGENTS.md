<!--
SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
SPDX-License-Identifier: Apache-2.0
-->

# Teleop ROS 2 Agent Notes

## Docker Validation

- This example needs ROS 2 plus the built `isaacteleop` wheel, which are not present in the dev container. Run/validate it inside the `examples/teleop_ros2/Dockerfile` image (the same path CI's `test-teleop-ros2` job uses), not directly on the host.
- To exercise it without live XR hardware, replay an MCAP fixture: build the image, run the installed `teleop_ros2_mcap_generator` to write a fixture, then run `teleop_ros2_node.py` with `-p mode:=<mode> -p mcap_replay_path:=<file>` and check topics (e.g. via `integration_tests/teleop_ros2_topic_verifier.py`). Replay mode does not launch CloudXR, so no GPU/NGC runtime is required. Share the fixture across containers with `-v /tmp:/tmp` and `--network host` for ROS 2 discovery.
- The image build disables some CI gates (`-DENABLE_CLANG_FORMAT_CHECK=OFF`, `-DBUILD_TESTING=OFF`), so a green Docker build does not mean C++ formatting or ctest pass. Validate those separately.
- When creating temporary Docker images for `examples/teleop_ros2` validation, remove them before finishing the task unless the user explicitly asks to keep them.

## Python Node Layout

- In `python/teleop_ros2_node.py`, preserve the existing grouped/sorted organization for global non-member helpers and `TeleopRos2Node` member functions: scan the surrounding order before inserting, and do not place helpers near call sites when the existing section is sorted.
- In Python integration test verifier code, do not use bare `assert` for runtime validation; Python optimization can disable it, so raise explicit exceptions from validators.
