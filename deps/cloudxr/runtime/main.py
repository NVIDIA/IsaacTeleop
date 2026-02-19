# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

import ctypes
import signal

lib = ctypes.CDLL("libcloudxr.so")
svc = ctypes.c_void_p()


def stop(sig, frame):
    lib.nv_cxr_service_stop(svc)


lib.nv_cxr_service_create(ctypes.byref(svc))
signal.signal(signal.SIGINT, stop)
signal.signal(signal.SIGTERM, stop)
lib.nv_cxr_service_start(svc)
lib.nv_cxr_service_join(svc)
lib.nv_cxr_service_destroy(svc)
