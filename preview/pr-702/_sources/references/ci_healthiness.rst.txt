.. SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
.. SPDX-License-Identifier: Apache-2.0

CI Healthiness Signals
======================

Isaac Teleop publishes baseline CI healthiness signals so maintainers can track
test coverage and open source dependency risk before adding hard blocking
thresholds. The first signal is intentionally scoped to the existing Ubuntu
CTest workflow so it reuses the build and test path that already gates pull
requests.

Coverage Report
---------------

The ``Build Ubuntu`` workflow generates a coverage report from the Ubuntu
Debug, x64, Python 3.11 CTest matrix entry. That entry builds the normal CMake
target graph with coverage compiler and linker flags, runs CTest, and then
publishes:

* ``coverage/summary.txt``: line-by-line text report.
* ``coverage/totals.txt``: aggregate coverage totals shown in the GitHub
  Actions step summary.
* ``coverage/cobertura.xml``: Cobertura XML for downstream dashboards.
* ``coverage/html``: browsable HTML coverage report.

The coverage job starts as an informational baseline. It should become a merge
gate only after the report scope is stable and maintainers agree on thresholds.

Path Toward 85 Percent Coverage
-------------------------------

Use the first stable coverage artifact as the baseline, then drive toward 85
percent coverage with this order of operations:

* Classify uncovered files by code area: production, generated, dependency,
  test-only, and intentionally integration-only.
* Tighten report scope before adding thresholds. Exclude generated code,
  third-party code, test fixtures, and other non-product paths; keep first-party
  ``src`` modules in scope.
* Add focused unit tests for low-dependency first-party modules first: schema
  conversion, tensor/type helpers, retargeting utilities, replay/session
  helpers, CloudXR launch validation, and teleop session manager state
  transitions.
* Add integration coverage for higher-risk paths that unit tests cannot model
  well: MCAP replay, OpenXR session lifecycle, CloudXR launch/error handling,
  and end-to-end teleop session setup.
* Add changed-code coverage reporting before enforcing a repository-wide
  threshold. This avoids blocking unrelated changes while the baseline is still
  improving.
* Raise the repository-level target incrementally after each code area has
  stable ownership and representative tests.

OSS License And Vulnerability Reporting
---------------------------------------

Isaac Teleop already enforces SPDX headers on changed source files with REUSE
pre-commit checks, and the license reference page documents the main
redistribution obligations. A complete OSS health signal should add dependency
reporting on top of that source-file check:

* Generate an SPDX or SBOM artifact from the resolved repository dependency
  graph.
* Include dependencies introduced by Python package metadata, CMake, vcpkg, and
  CMake ``FetchContent`` declarations.
* Compare the generated dependency list against vulnerability data and publish a
  CI artifact for review.
* Keep the first vulnerability report non-blocking until false positives,
  vendored dependencies, and intentionally bundled SDKs are triaged.
* Introduce severity-based merge gates only after the baseline report is
  stable.

For CMake and ``FetchContent`` dependencies, source-only scans can miss packages
that are resolved during configure/build. Validate the first dependency report
against ``deps/third_party/CMakeLists.txt``, plugin-specific CMake files, and
the vcpkg manifest paths used by the Ubuntu build. If anything is missing, add
a build-capture or generated-manifest step that runs with the same CMake
configuration used by CI.
