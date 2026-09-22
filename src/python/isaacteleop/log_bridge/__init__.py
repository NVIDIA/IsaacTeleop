# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""C++-to-Python logging bridge.

Routes isaacteleop::Logger records from in-process, pybind11-loaded C++
(src/core, src/viz) into Python's logging module, instead of the local
console/file sinks those loggers otherwise use.

isaacteleop/__init__.py calls install_python_sink() once on import, right
after logging_config.install() has built the handlers those records land in.
Applications do not need to call it.
"""

from ._log_bridge import install_python_sink

__all__ = [
    "install_python_sink",
]
