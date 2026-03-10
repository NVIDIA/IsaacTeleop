#!/bin/sh
# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
set -e

mkdir -p /openxr/.cloudxr/run
printf 'accepted\n' > /openxr/.cloudxr/run/eula_accepted

exec python -m isaacteleop.cloudxr
