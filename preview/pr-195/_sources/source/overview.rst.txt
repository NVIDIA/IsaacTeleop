.. SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
.. SPDX-License-Identifier: Apache-2.0

Overview
========

Isaac Teleop provides:

- **Teleop session manager** — manage teleop sessions and data pipelines
- **Retargeting engine** — map device outputs to robot embodiments (e.g. Unitree G1, dex hands)
- **Device I/O and schema** — standardized interfaces for controllers, hands, head, locomotion
- **Plugins** — extend support for new devices (e.g. Manus, OAK)

Project structure
-----------------

- ``src/core/`` — Core libraries (schema, retargeting, teleop session manager, device I/O)
- ``src/plugins/`` — Device and integration plugins
- ``examples/`` — Example scripts and apps

This overview can be expanded with architecture diagrams and detailed module descriptions.
