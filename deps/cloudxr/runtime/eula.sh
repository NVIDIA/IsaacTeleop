#!/bin/sh
# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

EULA=$(printf '%s' "${ACCEPT_EULA:-}" | tr '[:upper:]' '[:lower:]')
case "$EULA" in
  y|yes|1) exec "$@" ;;
  *)
    echo ""
    echo "The NVIDIA Software License Agreement (EULA) must be accepted before CloudXR"
    echo "Runtime in this container can start. The license terms can be viewed at"
    echo "https://developer.download.nvidia.com/cloudxr/EULA/NVIDIA_CloudXR_GA_License_without_Data_Collection_25Feb2025.pdf."
    echo ""
    echo 'Please accept the EULA by setting the ACCEPT_EULA environment variable.'
    echo 'e.g.: -e "ACCEPT_EULA=Y"'
    exit 1 ;;
esac
