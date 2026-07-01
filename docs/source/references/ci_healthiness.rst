.. SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
.. SPDX-License-Identifier: Apache-2.0

CTest Coverage Report
=====================

Isaac Teleop publishes an informational CTest coverage artifact from the
existing Ubuntu build workflow. The report is intentionally scoped to the
Ubuntu Debug, x64, Python 3.11 CTest matrix entry so it reuses the build and
test path that already gates pull requests.

The ``Build Ubuntu`` workflow generates a coverage report from the Ubuntu
Debug, x64, Python 3.11 CTest matrix entry. That entry builds the normal CMake
target graph with coverage compiler and linker flags, runs CTest, and then
publishes:

* ``coverage/summary.txt``: line-by-line text report.
* ``coverage/totals.txt``: aggregate coverage totals shown in the GitHub
  Actions step summary.
* ``coverage/cobertura.xml``: Cobertura XML for downstream dashboards.
* ``coverage/html``: browsable HTML coverage report.

The coverage artifact is a baseline signal, not a merge gate. Threshold and
coverage-improvement planning are handled outside the repository docs until the
report scope is stable and maintainers agree on enforcement policy.
