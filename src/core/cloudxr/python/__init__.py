# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""CloudXR runtime integration for isaacteleop.

Example:
    from isaacteleop.cloudxr import run
    run()  # blocks until SIGINT/SIGTERM

Or from the command line after pip install isaacteleop:
    python -m isaacteleop.cloudxr
"""

from .runtime import run

__all__ = ["run"]
