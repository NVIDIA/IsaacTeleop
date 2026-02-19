#!/bin/sh
# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
set -e

mkdir -p /openxr/run
cp -f /opt/cloudxr/libopenxr_cloudxr.so /openxr/
cp -f /opt/cloudxr/openxr_cloudxr.json /openxr/
rm -f /openxr/run/ipc_cloudxr /openxr/run/runtime_started
exec /eula.sh "$@"
