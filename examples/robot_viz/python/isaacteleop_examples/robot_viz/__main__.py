# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Entry point: ``python -m isaacteleop_examples.robot_viz``."""

import sys

from .app import main

if __name__ == "__main__":
    sys.exit(main(sys.argv))
