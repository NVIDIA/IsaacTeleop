#!/bin/sh
# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
set -e

mkdir -p /openxr/.cloudxr/run
printf 'accepted\n' > /openxr/.cloudxr/run/eula_accepted

# `run`, not `start`: the service must stay in the foreground as the
# container's main process.  `start` detaches and returns, which would exit
# the container and take the runtime with it.
exec python -m isaacteleop.cloudxr.service run
