# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""The CloudXR service: sole owner of the runtime process and the WSS proxy.

A host runs one service.  However it is started — ``service start``, a
container entrypoint, or a calling process via
``CloudXRLauncher(run_embedded=True)`` — everything else attaches to what it
started rather than starting its own.

``python -m isaacteleop.cloudxr.service`` is the CLI: ``run`` in the
foreground, ``start``/``stop``/``status``/``logs`` for a detached one.
"""

from ._service import CloudXRService

__all__ = ["CloudXRService"]
