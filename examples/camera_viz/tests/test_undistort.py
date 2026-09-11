# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
"""Undistort stage: LUT math (CPU, always) + GPU remap (skipped without CUDA)."""

from __future__ import annotations

import json
import math

import numpy as np
import pytest

from pipeline.undistort import (
    LensCalibration,
    UndistortSource,
    _fisheye_theta_from_radius,
    _project_fisheye,
    build_maps,
    derive_fov,
    resolve_settings,
)


def _fisheye_calib_dict(
    w=640, h=480, f=200.0, d=(0.02, -0.005, 0.001, 0.0), stereo=False
):
    K = [[f, 0.0, (w - 1) / 2.0], [0.0, f, (h - 1) / 2.0], [0.0, 0.0, 1.0]]
    eye = {"K": K, "D": list(d)}
    data = {"model": "fisheye", "image_size": [w, h]}
    if stereo:
        data["left"] = dict(eye)
        data["right"] = dict(eye)
    else:
        data.update(eye)
    return data


def _load(tmp_path, data) -> LensCalibration:
    p = tmp_path / "calib.json"
    p.write_text(json.dumps(data))
    return LensCalibration.load(p)


def test_parses_gr00t_schema_and_mono_fallback(tmp_path):
    stereo = _load(tmp_path, _fisheye_calib_dict(stereo=True))
    assert stereo.model == "fisheye"
    assert stereo.right is not None
    mono = _load(tmp_path, _fisheye_calib_dict(stereo=False))
    assert mono.right is None
    assert mono.left.K[0, 0] == pytest.approx(200.0)
    # No R_rect -> identity rotation.
    assert np.allclose(mono.left.R_cam_from_rect, np.eye(3))


def test_r_rect_transposed_when_inverse_missing(tmp_path):
    data = _fisheye_calib_dict(stereo=True)
    # 90-degree yaw as R_rect (camera->rectified); loader must store its
    # transpose (rectified->camera).
    R = [[0.0, 0.0, 1.0], [0.0, 1.0, 0.0], [-1.0, 0.0, 0.0]]
    data["left"]["R_rect"] = R
    calib = _load(tmp_path, data)
    assert np.allclose(calib.left.R_cam_from_rect, np.asarray(R).T)


def test_fisheye_projection_center_and_equidistant():
    K = np.array([[200.0, 0.0, 320.0], [0.0, 200.0, 240.0], [0.0, 0.0, 1.0]])
    D = np.zeros(4)
    # On-axis ray -> principal point.
    uv = _project_fisheye(np.array([[0.0, 0.0, 1.0]]), K, D)
    assert np.allclose(uv, [[320.0, 240.0]])
    # With zero distortion the model is pure equidistant: r = f * theta.
    theta = 0.5
    uv = _project_fisheye(np.array([[math.sin(theta), 0.0, math.cos(theta)]]), K, D)
    assert uv[0, 0] == pytest.approx(320.0 + 200.0 * theta)
    assert uv[0, 1] == pytest.approx(240.0)


def test_theta_solver_inverts_polynomial():
    D = np.array([0.03, -0.01, 0.002, -0.0004])
    for theta in (0.1, 0.6, 1.2):
        t2 = theta * theta
        r = theta * (1 + D[0] * t2 + D[1] * t2**2 + D[2] * t2**3 + D[3] * t2**4)
        assert _fisheye_theta_from_radius(r, D) == pytest.approx(theta, abs=1e-8)


def test_derive_fov_matches_border_angle(tmp_path):
    calib = _load(tmp_path, _fisheye_calib_dict(w=640, h=480, f=200.0, d=(0, 0, 0, 0)))
    hfov, vfov = derive_fov(calib, calib.left)
    # Pure equidistant: half-angle = half-width-pixels / f.
    assert hfov == pytest.approx(2.0 * ((640 - 1) / 2.0) / 200.0)
    assert vfov == pytest.approx(2.0 * ((480 - 1) / 2.0) / 200.0)


def test_maps_center_pixel_hits_principal_point(tmp_path):
    calib = _load(tmp_path, _fisheye_calib_dict())
    for projection in ("rectilinear", "cylindrical", "equirect"):
        # The test lens covers ~178 degrees; rectilinear needs a crop
        # (the guard for that is tested separately below).
        overrides = (
            {"hfov_deg": 100, "vfov_deg": 80} if projection == "rectilinear" else {}
        )
        s = resolve_settings(calib, projection, overrides)
        mx, my = build_maps(
            calib,
            calib.left,
            projection,
            s.out_width,
            s.out_height,
            s.hfov_rad,
            s.vfov_rad,
        )
        assert mx.shape == (s.out_height, s.out_width)
        cy, cx = s.out_height // 2, s.out_width // 2
        # Output center looks down the optical axis -> principal point,
        # to within half an output pixel of angular quantization.
        assert abs(mx[cy, cx] - calib.left.K[0, 2]) < 2.0
        assert abs(my[cy, cx] - calib.left.K[1, 2]) < 2.0
        # Along the principal axes the derived FOV never samples outside
        # the source (grid CORNERS may — the display shows them black,
        # matching the source's own coverage limits).
        mid_row_x = mx[cy, :]
        mid_col_y = my[:, cx]
        assert mid_row_x.min() >= -1.0 and mid_row_x.max() <= 640.0
        assert mid_col_y.min() >= -1.0 and mid_col_y.max() <= 480.0


def test_cylindrical_map_is_equal_angle_horizontally(tmp_path):
    # With zero distortion, equal azimuth steps in the OUTPUT must map to
    # equal theta steps at the horizon row — i.e. equal pixel steps in an
    # equidistant source. That's the property the CylinderLayer relies on.
    calib = _load(tmp_path, _fisheye_calib_dict(d=(0, 0, 0, 0)))
    s = resolve_settings(calib, "cylindrical", {})
    mx, _ = build_maps(
        calib,
        calib.left,
        "cylindrical",
        s.out_width,
        s.out_height,
        s.hfov_rad,
        s.vfov_rad,
    )
    row = mx[s.out_height // 2, :]
    steps = np.diff(row)
    assert steps.std() / steps.mean() < 1e-3


def test_rectilinear_rejects_degenerate_fov(tmp_path):
    calib = _load(tmp_path, _fisheye_calib_dict(f=80.0))  # ~4.0 rad hfov
    with pytest.raises(ValueError, match="rectilinear"):
        resolve_settings(calib, "rectilinear", {})
    # Cylindrical accepts the same lens.
    s = resolve_settings(calib, "cylindrical", {})
    assert s.hfov_rad > math.radians(160.0)


def test_overrides(tmp_path):
    calib = _load(tmp_path, _fisheye_calib_dict())
    s = resolve_settings(
        calib,
        "cylindrical",
        {"hfov_deg": 90, "vfov_deg": 60, "out_width": 800, "out_height": 500},
    )
    assert s.hfov_rad == pytest.approx(math.radians(90))
    assert s.vfov_rad == pytest.approx(math.radians(60))
    assert (s.out_width, s.out_height) == (800, 500)


# ── GPU path ──────────────────────────────────────────────────────────


def _gpu_available() -> bool:
    try:
        import cupy as cp

        return cp.cuda.runtime.getDeviceCount() > 0
    except Exception:
        return False


@pytest.mark.skipif(not _gpu_available(), reason="no CUDA GPU")
def test_gpu_remap_identity_and_source(tmp_path):
    import cupy as cp

    from pipeline.interface import Frame, SourceSpec

    calib = _load(tmp_path, _fisheye_calib_dict(w=64, h=48, f=40.0, d=(0, 0, 0, 0)))
    s = resolve_settings(calib, "cylindrical", {})

    class OneShot:
        spec = SourceSpec(name="t", width=64, height=48)

        def __init__(self):
            img = cp.zeros((48, 64, 4), dtype=cp.uint8)
            img[:, :, 0] = cp.arange(64, dtype=cp.uint8)[None, :] * 3  # R ramp
            img[:, :, 3] = 255
            self._frame = Frame(image=img, timestamp_ns=0, source_id="t")

        def start(self):
            pass

        def stop(self):
            pass

        def latest(self):
            f, self._frame = self._frame, None
            return f

    src = UndistortSource(OneShot(), calib, s)
    assert (src.spec.width, src.spec.height) == (s.out_width, s.out_height)
    out = src.latest()
    assert out is not None
    arr = cp.asnumpy(out.image)
    assert arr.shape == (s.out_height, s.out_width, 4)
    assert (arr[:, :, 3] == 255).all()
    # Center of a distortion-free remap shows the center of the ramp.
    assert abs(int(arr[s.out_height // 2, s.out_width // 2, 0]) - 31 * 3) <= 6
    # Mailbox contract: no new inner frame -> None.
    assert src.latest() is None
