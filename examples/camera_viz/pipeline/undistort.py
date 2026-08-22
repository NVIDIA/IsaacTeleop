# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
"""Lens undistortion stage: calibrated remap into a display-matched projection.

Pipeline: a per-eye sampling LUT is precomputed ONCE on the CPU from the
camera calibration (intrinsics + distortion + optional stereo
rectification), then every camera frame is remapped on the GPU with a
single bilinear gather before it reaches the layer. The remap target
projection is chosen to match the display surface, so the shown image is
angle-correct end to end:

  ==========  ===================  =============================
  shape       remap projection     display parameterization
  ==========  ===================  =============================
  quad        rectilinear          planar (pinhole)
  cylinder    cylindrical          equal-angle x, planar y
  equirect    equirectangular      equal-angle x and y
  ==========  ===================  =============================

Rectilinear stretches toward the edges and cannot reach 180 degrees;
for wide-FOV fisheye heads (Tianji shw5g ~130 degrees) the cylindrical
target keeps the full FOV at uniform angular resolution.

Calibration JSON schema (the gr00t shw5g ChArUco format is accepted
verbatim): top-level ``model`` ("fisheye" for Kannala-Brandt theta
polynomial, "brown"/"pinhole" for Brown-Conrady), ``image_size``
[W, H], and either per-eye ``left``/``right`` blocks or top-level
``K``/``D`` for mono. Each eye block: ``K`` (3x3), ``D`` (4 fisheye or
4/5/8 Brown coefficients), optional ``R_rect_inv``/``R_rect`` (stereo
rectification rotation; folded into the LUT so stereo pairs come out
row-aligned).

Coordinates follow OpenCV camera conventions (x right, y down,
z forward).
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Tuple

import numpy as np

from .interface import Frame, FrameSource, SourceSpec

PROJECTIONS = ("rectilinear", "cylindrical", "equirect")


# ----------------------------------------------------------------------
# Calibration parsing
# ----------------------------------------------------------------------


@dataclass(frozen=True)
class EyeCalibration:
    K: np.ndarray  # (3, 3) float64
    D: np.ndarray  # distortion coefficients, model-dependent length
    R_cam_from_rect: np.ndarray  # (3, 3): rectified-frame ray -> camera-frame ray


@dataclass(frozen=True)
class LensCalibration:
    model: str  # "fisheye" | "brown"
    image_size: Tuple[int, int]  # (W, H)
    left: EyeCalibration
    right: Optional[EyeCalibration]

    @staticmethod
    def load(path: str | Path) -> "LensCalibration":
        with open(path) as f:
            data = json.load(f)
        model = str(data.get("model", "fisheye")).lower()
        if model in ("pinhole", "brown", "brown-conrady", "plumb_bob"):
            model = "brown"
        elif model in ("fisheye", "kannala-brandt", "kb4", "equidistant"):
            model = "fisheye"
        else:
            raise ValueError(
                f"undistort: unknown calibration model {model!r} in {path}"
            )
        if "image_size" not in data:
            raise ValueError(f"undistort: calibration {path} missing image_size [W, H]")
        w, h = (int(v) for v in data["image_size"])

        def eye(block: dict) -> EyeCalibration:
            K = np.asarray(block["K"], dtype=np.float64).reshape(3, 3)
            D = np.asarray(block.get("D", []), dtype=np.float64).reshape(-1)
            if "R_rect_inv" in block:
                R = np.asarray(block["R_rect_inv"], dtype=np.float64).reshape(3, 3)
            elif "R_rect" in block:
                # R_rect maps camera rays -> rectified rays (OpenCV
                # convention); the LUT walks the other way.
                R = np.asarray(block["R_rect"], dtype=np.float64).reshape(3, 3).T
            else:
                R = np.eye(3)
            return EyeCalibration(K=K, D=D, R_cam_from_rect=R)

        if "left" in data:
            left = eye(data["left"])
            right = eye(data["right"]) if "right" in data else None
        elif "K" in data:
            left = eye(data)
            right = None
        else:
            raise ValueError(
                f"undistort: calibration {path} has neither left/right blocks nor top-level K"
            )
        return LensCalibration(model=model, image_size=(w, h), left=left, right=right)


# ----------------------------------------------------------------------
# Lens model: camera-frame rays -> source pixel coordinates
# ----------------------------------------------------------------------


def _project_fisheye(dirs: np.ndarray, K: np.ndarray, D: np.ndarray) -> np.ndarray:
    """Kannala-Brandt (OpenCV fisheye): theta_d = theta(1 + k1 t^2 + ... + k4 t^8)."""
    x, y, z = dirs[..., 0], dirs[..., 1], dirs[..., 2]
    r_xy = np.sqrt(x * x + y * y)
    theta = np.arctan2(r_xy, z)
    k = np.zeros(4)
    k[: min(4, D.size)] = D[:4]
    t2 = theta * theta
    theta_d = theta * (1.0 + k[0] * t2 + k[1] * t2**2 + k[2] * t2**3 + k[3] * t2**4)
    with np.errstate(invalid="ignore", divide="ignore"):
        scale = np.where(r_xy > 1e-9, theta_d / r_xy, 1.0)
    xd, yd = x * scale, y * scale
    u = K[0, 0] * (xd + (K[0, 1] / K[0, 0]) * yd) + K[0, 2]
    v = K[1, 1] * yd + K[1, 2]
    # theta >= pi/2 is behind-the-lens for practical FOVs derived below;
    # keep whatever the polynomial produced — out-of-image lands black.
    return np.stack([u, v], axis=-1)


def _project_brown(dirs: np.ndarray, K: np.ndarray, D: np.ndarray) -> np.ndarray:
    """Brown-Conrady with OpenCV coefficient order (k1 k2 p1 p2 [k3 [k4 k5 k6]])."""
    x, y, z = dirs[..., 0], dirs[..., 1], dirs[..., 2]
    valid = z > 1e-6
    zs = np.where(valid, z, 1.0)
    xp, yp = x / zs, y / zs
    d = np.zeros(8)
    d[: min(8, D.size)] = D[:8]
    k1, k2, p1, p2, k3, k4, k5, k6 = d
    r2 = xp * xp + yp * yp
    radial = (1.0 + k1 * r2 + k2 * r2**2 + k3 * r2**3) / (
        1.0 + k4 * r2 + k5 * r2**2 + k6 * r2**3
    )
    xd = xp * radial + 2.0 * p1 * xp * yp + p2 * (r2 + 2.0 * xp * xp)
    yd = yp * radial + p1 * (r2 + 2.0 * yp * yp) + 2.0 * p2 * xp * yp
    u = K[0, 0] * xd + K[0, 1] * yd + K[0, 2]
    v = K[1, 1] * yd + K[1, 2]
    # Rays at/behind the image plane can't be sampled: push out of range.
    u = np.where(valid, u, -1e9)
    v = np.where(valid, v, -1e9)
    return np.stack([u, v], axis=-1)


def _fisheye_theta_from_radius(r_norm: float, D: np.ndarray) -> float:
    """Invert theta_d(theta) = r for the KB polynomial (Newton, monotonic range)."""
    k = np.zeros(4)
    k[: min(4, D.size)] = D[:4]
    theta = min(r_norm, math.pi / 2.0)  # r is a decent seed for small distortion
    for _ in range(20):
        t2 = theta * theta
        f = (
            theta * (1.0 + k[0] * t2 + k[1] * t2**2 + k[2] * t2**3 + k[3] * t2**4)
            - r_norm
        )
        fp = (
            1.0
            + 3.0 * k[0] * t2
            + 5.0 * k[1] * t2**2
            + 7.0 * k[2] * t2**3
            + 9.0 * k[3] * t2**4
        )
        step = f / fp
        theta -= step
        if abs(step) < 1e-10:
            break
    return max(theta, 0.0)


def derive_fov(calib: LensCalibration, eye: EyeCalibration) -> Tuple[float, float]:
    """(hfov, vfov) in radians covered by the source image, symmetric about
    the optical axis (min of the two half-angles per axis, so a symmetric
    output grid never samples outside the image)."""
    w, h = calib.image_size
    fx, fy = eye.K[0, 0], eye.K[1, 1]
    cx, cy = eye.K[0, 2], eye.K[1, 2]
    half_x_px = min(cx, (w - 1) - cx)
    half_y_px = min(cy, (h - 1) - cy)
    if calib.model == "fisheye":
        half_h = _fisheye_theta_from_radius(half_x_px / fx, eye.D)
        half_v = _fisheye_theta_from_radius(half_y_px / fy, eye.D)
    else:
        # Brown distortion is small at typical pinhole FOVs; the ideal
        # angle is a good bound (out-of-image rays land black anyway).
        half_h = math.atan(half_x_px / fx)
        half_v = math.atan(half_y_px / fy)
    return 2.0 * half_h, 2.0 * half_v


# ----------------------------------------------------------------------
# Output-projection ray grids
# ----------------------------------------------------------------------


def _ray_grid(
    projection: str, out_w: int, out_h: int, hfov: float, vfov: float
) -> np.ndarray:
    """(out_h, out_w, 3) unit-scale ray directions in the RECTIFIED frame,
    OpenCV convention (x right, y down, z forward), pixel centers."""
    u = (np.arange(out_w, dtype=np.float64) + 0.5) / out_w  # 0..1 left->right
    v = (np.arange(out_h, dtype=np.float64) + 0.5) / out_h  # 0..1 top->bottom
    uu, vv = np.meshgrid(u, v)
    if projection == "rectilinear":
        x = (uu - 0.5) * 2.0 * math.tan(hfov / 2.0)
        y = (vv - 0.5) * 2.0 * math.tan(vfov / 2.0)
        z = np.ones_like(x)
    elif projection == "cylindrical":
        # Equal-angle horizontally, planar vertically: matches how an
        # XrCompositionLayerCylinderKHR of central_angle == hfov samples
        # its texture (height h at azimuth psi -> direction (sin, h, cos)).
        psi = (uu - 0.5) * hfov
        x = np.sin(psi)
        y = (vv - 0.5) * 2.0 * math.tan(vfov / 2.0)
        z = np.cos(psi)
    elif projection == "equirect":
        # Equal-angle both axes: matches XrCompositionLayerEquirect2KHR
        # with central_horizontal_angle == hfov, vertical span == vfov.
        psi = (uu - 0.5) * hfov
        phi = (vv - 0.5) * vfov  # positive = down (OpenCV y-down)
        x = np.cos(phi) * np.sin(psi)
        y = np.sin(phi)
        z = np.cos(phi) * np.cos(psi)
    else:
        raise ValueError(f"undistort: unknown projection {projection!r}")
    return np.stack([x, y, z], axis=-1)


def build_maps(
    calib: LensCalibration,
    eye: EyeCalibration,
    projection: str,
    out_w: int,
    out_h: int,
    hfov: float,
    vfov: float,
) -> Tuple[np.ndarray, np.ndarray]:
    """Sampling LUT: for each output pixel, the (sub-pixel) source
    coordinate to bilinearly fetch. Returns (map_x, map_y) float32 of
    shape (out_h, out_w); out-of-image entries stay out of range and the
    remap kernel writes opaque black there."""
    rays = _ray_grid(projection, out_w, out_h, hfov, vfov)
    cam_rays = rays @ eye.R_cam_from_rect.T
    if calib.model == "fisheye":
        uv = _project_fisheye(cam_rays, eye.K, eye.D)
    else:
        uv = _project_brown(cam_rays, eye.K, eye.D)
    return (
        np.ascontiguousarray(uv[..., 0], dtype=np.float32),
        np.ascontiguousarray(uv[..., 1], dtype=np.float32),
    )


# ----------------------------------------------------------------------
# GPU remap (CuPy raw kernel, bilinear RGBA8)
# ----------------------------------------------------------------------

_REMAP_KERNEL_SRC = r"""
extern "C" __global__ void remap_rgba8(
    const unsigned char* __restrict__ src, int src_w, int src_h, long long src_pitch,
    const float* __restrict__ map_x, const float* __restrict__ map_y,
    unsigned char* __restrict__ dst, int dst_w, int dst_h)
{
    int x = blockIdx.x * blockDim.x + threadIdx.x;
    int y = blockIdx.y * blockDim.y + threadIdx.y;
    if (x >= dst_w || y >= dst_h) return;
    long long o = ((long long)y * dst_w + x) * 4;
    float sx = map_x[(long long)y * dst_w + x];
    float sy = map_y[(long long)y * dst_w + x];
    if (!(sx >= 0.0f && sy >= 0.0f && sx <= (float)(src_w - 1) && sy <= (float)(src_h - 1))) {
        dst[o] = 0; dst[o + 1] = 0; dst[o + 2] = 0; dst[o + 3] = 255;
        return;
    }
    int x0 = (int)sx, y0 = (int)sy;
    int x1 = min(x0 + 1, src_w - 1), y1 = min(y0 + 1, src_h - 1);
    float fx = sx - (float)x0, fy = sy - (float)y0;
    const unsigned char* p00 = src + (long long)y0 * src_pitch + (long long)x0 * 4;
    const unsigned char* p01 = src + (long long)y0 * src_pitch + (long long)x1 * 4;
    const unsigned char* p10 = src + (long long)y1 * src_pitch + (long long)x0 * 4;
    const unsigned char* p11 = src + (long long)y1 * src_pitch + (long long)x1 * 4;
    #pragma unroll
    for (int c = 0; c < 3; ++c) {
        float top = (float)p00[c] + fx * ((float)p01[c] - (float)p00[c]);
        float bot = (float)p10[c] + fx * ((float)p11[c] - (float)p10[c]);
        dst[o + c] = (unsigned char)(top + fy * (bot - top) + 0.5f);
    }
    dst[o + 3] = 255;
}
"""


class GpuRemapper:
    """One eye's persistent LUT + output buffer; remap() is a single
    kernel launch on the producer's CUDA stream."""

    def __init__(
        self, map_x: np.ndarray, map_y: np.ndarray, src_size: Tuple[int, int]
    ) -> None:
        import cupy as cp

        self._cp = cp
        self._map_x_np = map_x
        self._map_y_np = map_y
        self._src_w, self._src_h = src_size
        self._out_h, self._out_w = map_x.shape
        # GPU buffers materialize lazily on the DEVICE the frames arrive
        # on (multi-GPU hosts: the viz session may live on a different
        # GPU than the capture source; launching a kernel with
        # cross-device pointers is an illegal access).
        self._device_id: Optional[int] = None
        self._kernel = None
        self._map_x = None
        self._map_y = None
        self._out = None

    def _ensure_device(self, device_id: int) -> None:
        if self._device_id == device_id:
            return
        cp = self._cp
        with cp.cuda.Device(device_id):
            self._kernel = cp.RawKernel(_REMAP_KERNEL_SRC, "remap_rgba8")
            self._map_x = cp.asarray(self._map_x_np)
            self._map_y = cp.asarray(self._map_y_np)
            self._out = cp.empty((self._out_h, self._out_w, 4), dtype=cp.uint8)
        self._device_id = device_id

    def remap(self, image, stream: int = 0):
        """image: HxWx4 uint8 __cuda_array_interface__ array (C-contiguous
        rows; pitch honored). Returns the persistent output CuPy array —
        valid until the next remap() call for this eye."""
        cp = self._cp
        src = cp.asarray(image)
        if (
            src.shape[0] != self._src_h
            or src.shape[1] != self._src_w
            or src.shape[2] != 4
        ):
            raise ValueError(
                f"undistort: frame {src.shape[1]}x{src.shape[0]} does not match "
                f"calibration image_size {self._src_w}x{self._src_h}"
            )
        self._ensure_device(src.device.id)
        pitch = src.strides[0]
        block = (16, 16, 1)
        grid = (
            (self._out_w + block[0] - 1) // block[0],
            (self._out_h + block[1] - 1) // block[1],
            1,
        )
        with cp.cuda.Device(src.device.id):
            ctx = cp.cuda.ExternalStream(stream) if stream else cp.cuda.Stream.null
            with ctx:
                self._kernel(
                    grid,
                    block,
                    (
                        src,
                        np.int32(self._src_w),
                        np.int32(self._src_h),
                        np.int64(pitch),
                        self._map_x,
                        self._map_y,
                        self._out,
                        np.int32(self._out_w),
                        np.int32(self._out_h),
                    ),
                )
        return self._out


# ----------------------------------------------------------------------
# FrameSource wrapper
# ----------------------------------------------------------------------


@dataclass(frozen=True)
class UndistortSettings:
    """Resolved undistort parameters for one camera (see camera_viz's
    ``calib:`` / ``undistort:`` YAML keys)."""

    calib_path: str
    projection: str  # one of PROJECTIONS
    out_width: int
    out_height: int
    hfov_rad: float
    vfov_rad: float


def resolve_settings(
    calib: LensCalibration,
    projection: str,
    overrides: dict,
) -> UndistortSettings:
    """Fill FOV / output size from the calibration unless overridden.
    FOV comes from the LEFT eye (stereo rigs are near-identical and a
    shared output grid keeps the pair rectified)."""
    if projection not in PROJECTIONS:
        raise ValueError(
            f"undistort: projection must be one of {'|'.join(PROJECTIONS)}, got {projection!r}"
        )
    auto_h, auto_v = derive_fov(calib, calib.left)
    hfov = (
        math.radians(float(overrides["hfov_deg"]))
        if "hfov_deg" in overrides
        else auto_h
    )
    vfov = (
        math.radians(float(overrides["vfov_deg"]))
        if "vfov_deg" in overrides
        else auto_v
    )
    if projection == "rectilinear":
        # tan() blows up approaching 180 degrees; refuse silly outputs.
        limit = math.radians(160.0)
        if hfov >= limit or vfov >= limit:
            raise ValueError(
                "undistort: rectilinear output beyond 160 degrees is degenerate — "
                "use shape: cylinder (or equirect) for wide-FOV lenses, or pass "
                "undistort.hfov_deg / vfov_deg to crop"
            )
    src_w, src_h = calib.image_size
    out_w = int(overrides.get("out_width", src_w))
    out_h = int(overrides.get("out_height", src_h))
    return UndistortSettings(
        calib_path="",
        projection=projection,
        out_width=out_w,
        out_height=out_h,
        hfov_rad=hfov,
        vfov_rad=vfov,
    )


class UndistortSource(FrameSource):
    """Wraps a FrameSource and remaps every new frame through the
    calibrated LUT (per eye for stereo). latest() preserves the inner
    mailbox contract: the remap runs exactly once per new frame."""

    def __init__(
        self, inner: FrameSource, calib: LensCalibration, settings: UndistortSettings
    ) -> None:
        self._inner = inner
        self._settings = settings
        maps_l = build_maps(
            calib,
            calib.left,
            settings.projection,
            settings.out_width,
            settings.out_height,
            settings.hfov_rad,
            settings.vfov_rad,
        )
        self._left = GpuRemapper(*maps_l, calib.image_size)
        self._right: Optional[GpuRemapper] = None
        if calib.right is not None:
            maps_r = build_maps(
                calib,
                calib.right,
                settings.projection,
                settings.out_width,
                settings.out_height,
                settings.hfov_rad,
                settings.vfov_rad,
            )
            self._right = GpuRemapper(*maps_r, calib.image_size)
        self._spec = SourceSpec(
            name=inner.spec.name,
            width=settings.out_width,
            height=settings.out_height,
            pixel_format=inner.spec.pixel_format,
        )

    @property
    def spec(self) -> SourceSpec:
        return self._spec

    @property
    def settings(self) -> UndistortSettings:
        return self._settings

    def start(self) -> None:
        self._inner.start()

    def stop(self) -> None:
        self._inner.stop()

    def latest(self) -> Optional[Frame]:
        frame = self._inner.latest()
        if frame is None:
            return None
        image = self._left.remap(frame.image, stream=frame.stream)
        right = None
        if frame.image_right is not None:
            # Stereo frame: right eye through its own LUT; without a
            # right calibration block, fall back to the left LUT (mono
            # calib on a stereo rig — better than nothing, warned at load).
            remapper = self._right if self._right is not None else self._left
            if remapper is self._left:
                # The left remapper's output buffer would be overwritten;
                # copy before reusing it for the right eye.
                image = image.copy()
            right = remapper.remap(frame.image_right, stream=frame.stream)
        return Frame(
            image=image,
            timestamp_ns=frame.timestamp_ns,
            source_id=frame.source_id,
            stream=frame.stream,
            image_right=right,
        )
