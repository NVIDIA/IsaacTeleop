# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
"""Validate that VizBuffer + HostImage interoperate with NumPy / CuPy / PyTorch
via the standard array-interface protocols.

The protocols are passive (just dicts), so these tests don't require us to
import the third-party libs at module load. Tests gracefully skip when a
library isn't installed — exercises the contract on whatever CI has.
"""

from __future__ import annotations

import importlib.util

import numpy as np
import pytest

import isaacteleop.viz as viz


def _has(mod_name: str) -> bool:
    return importlib.util.find_spec(mod_name) is not None


# ── Protocol dict shape ──────────────────────────────────────────────


def test_host_buffer_exposes_array_interface_dict():
    img = viz.HostImage(viz.Resolution(8, 4), viz.PixelFormat.kRGBA8)
    buf = img.view()
    iface = buf.__array_interface__
    assert iface["shape"] == (4, 8, 4)
    assert iface["typestr"] == "|u1"
    assert iface["version"] == 3
    ptr, read_only = iface["data"]
    assert isinstance(ptr, int)
    # Writable by default — producer owns the memory; consumers that
    # need read-only semantics should copy.
    assert read_only is False


def test_host_buffer_rejects_cuda_array_interface():
    img = viz.HostImage(viz.Resolution(8, 4), viz.PixelFormat.kRGBA8)
    buf = img.view()
    with pytest.raises(AttributeError):
        _ = buf.__cuda_array_interface__


def test_device_buffer_exposes_cuda_array_interface_dict():
    # Construct a kDevice VizBuffer manually with a non-null pointer
    # (any integer works — the interface dict is metadata).
    buf = viz.VizBuffer()
    buf.data = 0xDEADBEEF
    buf.width = 1920
    buf.height = 1080
    buf.format = viz.PixelFormat.kRGBA8
    buf.space = viz.MemorySpace.kDevice
    iface = buf.__cuda_array_interface__
    assert iface["shape"] == (1080, 1920, 4)
    assert iface["typestr"] == "|u1"
    assert iface["version"] == 3
    assert iface["data"] == (0xDEADBEEF, False)


def test_device_buffer_rejects_array_interface():
    buf = viz.VizBuffer()
    buf.data = 0x1
    buf.width = 1
    buf.height = 1
    buf.format = viz.PixelFormat.kRGBA8
    buf.space = viz.MemorySpace.kDevice
    with pytest.raises(AttributeError):
        _ = buf.__array_interface__


def test_d32f_format_produces_2d_shape():
    buf = viz.VizBuffer()
    buf.data = 0x1
    buf.width = 16
    buf.height = 9
    buf.format = viz.PixelFormat.kD32F
    buf.space = viz.MemorySpace.kDevice
    iface = buf.__cuda_array_interface__
    assert iface["shape"] == (9, 16)
    assert iface["typestr"] == "<f4"


def test_null_data_raises():
    buf = viz.VizBuffer()
    buf.width = 8
    buf.height = 4
    buf.format = viz.PixelFormat.kRGBA8
    buf.space = viz.MemorySpace.kDevice
    with pytest.raises(RuntimeError):
        _ = buf.__cuda_array_interface__


# ── Round-trip: NumPy ───────────────────────────────────────────────


def test_numpy_zero_copy_view_of_host_image():
    img = viz.HostImage(viz.Resolution(8, 4), viz.PixelFormat.kRGBA8)
    arr = np.asarray(img)
    assert arr.shape == (4, 8, 4)
    assert arr.dtype == np.uint8
    # Zero-copy: writing through arr is observable via a fresh view.
    arr[0, 0] = (1, 2, 3, 4)
    arr2 = np.asarray(img)
    assert tuple(arr2[0, 0]) == (1, 2, 3, 4)


# ── Round-trip: CuPy ────────────────────────────────────────────────


@pytest.mark.skipif(not _has("cupy"), reason="cupy not installed")
def test_cupy_round_trip():
    import cupy as cp

    if cp.cuda.runtime.getDeviceCount() == 0:
        pytest.skip("no CUDA device")

    # Build a CuPy RGBA8 image, expose it as a VizBuffer, read it back
    # via the cuda interface. Validates both directions of the protocol.
    src = cp.asarray((np.arange(4 * 8 * 4) % 256).astype(np.uint8).reshape(4, 8, 4))
    src = cp.ascontiguousarray(src)

    buf = viz.VizBuffer()
    buf.data = int(src.data.ptr)
    buf.width = 8
    buf.height = 4
    buf.format = viz.PixelFormat.kRGBA8
    buf.space = viz.MemorySpace.kDevice

    # CuPy reads our __cuda_array_interface__.
    view = cp.asarray(buf)
    assert view.shape == (4, 8, 4)
    assert view.dtype == cp.uint8
    # Round-trip equality: cp.asnumpy(view) == src.
    assert cp.array_equal(view, src)


# ── Round-trip: PyTorch ─────────────────────────────────────────────


@pytest.mark.skipif(not _has("torch"), reason="torch not installed")
def test_torch_host_round_trip():
    import torch

    img = viz.HostImage(viz.Resolution(8, 4), viz.PixelFormat.kRGBA8)
    arr = np.asarray(img)
    arr[:] = 42
    # torch.as_tensor consumes __array_interface__ for host data.
    t = torch.as_tensor(arr)
    assert t.shape == (4, 8, 4)
    assert t.dtype == torch.uint8
    assert int(t[0, 0, 0].item()) == 42


@pytest.mark.skipif(not _has("torch"), reason="torch not installed")
def test_torch_cuda_round_trip():
    import torch

    if not torch.cuda.is_available():
        pytest.skip("no CUDA-enabled torch")

    # Make a CUDA tensor, expose its pointer through a VizBuffer, let
    # torch reconstruct via __cuda_array_interface__.
    src = torch.arange(4 * 8 * 4, dtype=torch.uint8, device="cuda").reshape(4, 8, 4)
    src = src.contiguous()

    buf = viz.VizBuffer()
    buf.data = src.data_ptr()
    buf.width = 8
    buf.height = 4
    buf.format = viz.PixelFormat.kRGBA8
    buf.space = viz.MemorySpace.kDevice

    # torch.as_tensor accepts __cuda_array_interface__ since torch 1.8+.
    view = torch.as_tensor(buf, device="cuda")
    assert view.shape == (4, 8, 4)
    assert view.dtype == torch.uint8
    assert torch.equal(view, src)
