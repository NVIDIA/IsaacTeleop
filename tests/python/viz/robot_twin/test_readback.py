# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""The OpenGL -> CUDA readback, on a real GPU and with no headset.

The only test here that touches hardware, and it skips loudly without it. What it buys
is the two conversions that are otherwise invisible until someone is wearing a headset:
the y flip and the depth inversion. It stops at ProjectionLayer.submit and covers
nothing downstream.

The scene is one box on a mocap body, built inline: what is measured is where drawn
pixels land, and a single geom the test can park anywhere is the whole requirement.
"""

import ctypes
import math

import numpy as np
import pytest

scene_module = pytest.importorskip(
    "isaacteleop.viz.robot.scene", reason="the robot twin backend is not built"
)
frames = pytest.importorskip("isaacteleop.viz.robot.frames")

SceneTwin = scene_module.SceneTwin

NEAR_Z = 0.05
FAR_Z = 50.0
BOX = "box"
#: Half-extent of the cube below, in metres.
BOX_HALF_SIZE = 0.02
# A 4 cm cube on a mocap body, so the fixture can park it anywhere by publishing.
SCENE = """
<mujoco>
  <worldbody>
    <body name="box" mocap="true">
      <geom name="box_geom" type="box" size="0.02 0.02 0.02" rgba="1 1 1 1" group="2"/>
    </body>
  </worldbody>
</mujoco>
"""

W = H = 256
HALF_FOV = math.radians(45.0)
BOX_DISTANCE = 0.6  # metres straight ahead of the eye
BOX_OFFSET = 0.15  # metres off-axis, comfortably outside the box's own size


@pytest.fixture(scope="module")
def rendered(tmp_path_factory):
    """A live SceneTwin plus a device-to-host copier, or a skip saying why.

    Drives the shipped twin rather than a Renderer of its own, so what is measured is
    the path the app actually takes: publish, apply, forward, update_scene, render.
    """
    path = tmp_path_factory.mktemp("scene") / "readback.xml"
    path.write_text(SCENE)
    twin = SceneTwin(path)

    try:
        twin.create(W, H, 2, near_z=NEAR_Z, far_z=FAR_Z)
    except Exception as exc:  # noqa: BLE001 -- no GPU, no GL, or the wrong device
        twin.destroy()
        # Includes the multi-GPU case, where the EGL device and the process's
        # CUDA device differ and the fix is GlContext(device_index=...).
        pytest.skip(f"renderer unavailable: {exc}")
    cuda = ctypes.CDLL("libcuda.so.1")

    def read(view, is_depth):
        img = twin.depth(view) if is_depth else twin.color(view)
        shape = (H, W) if is_depth else (H, W, 4)
        out = np.empty(shape, dtype=np.float32 if is_depth else np.uint8)
        rc = cuda.cuMemcpyDtoH_v2(
            out.ctypes.data_as(ctypes.c_void_p),
            ctypes.c_uint64(img.__cuda_array_interface__["data"][0]),
            ctypes.c_size_t(out.nbytes),
        )
        assert rc == 0, f"cuMemcpyDtoH_v2 -> {rc}"
        return out

    def render(xr_offset, eye_separation=0.0):
        """Park the box at `xr_offset` from the eye and draw both views."""
        twin.publish(
            bodies={BOX: (frames.mj_from_xr_pos(xr_offset), (1.0, 0.0, 0.0, 0.0))}
        )
        poses, fovs = [], []
        for sign in (-1.0, 1.0):
            poses += [sign * eye_separation, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0]
            fovs += [-HALF_FOV, HALF_FOV, HALF_FOV, -HALF_FOV]
        twin.render(poses, fovs)

    yield render, read
    twin.destroy()


def _drawn_centre(color):
    """(row, col) centre of the drawn pixels; alpha 0 is 'show passthrough'."""
    drawn = color[..., 3] > 0
    assert drawn.any(), "nothing was drawn"
    return np.flatnonzero(drawn.any(axis=1)).mean(), np.flatnonzero(
        drawn.any(axis=0)
    ).mean()


def test_something_is_drawn_at_all(rendered):
    render, read = rendered
    render([0.0, 0.0, -BOX_DISTANCE])
    color = read(0, is_depth=False)
    assert (color[..., 3] > 0).any(), (
        "the whole frame is transparent -- mjr_render drew into another framebuffer, "
        "or the blit missed"
    )
    assert set(np.unique(color[..., 3])) <= {0, 255}, (
        "alpha must be 0 (passthrough) or 255 (opaque); a partial alpha means blending "
        "leaked into the readback pass"
    )


def test_row_zero_is_the_top_of_the_operators_view(rendered):
    """The y flip: OpenGL renders bottom-up, XR swapchains are top-down, and
    nothing short of a headset would show the whole scene upside down."""
    render, read = rendered
    render([0.0, BOX_OFFSET, -BOX_DISTANCE])
    above, _ = _drawn_centre(read(0, is_depth=False))
    render([0.0, -BOX_OFFSET, -BOX_DISTANCE])
    below, _ = _drawn_centre(read(0, is_depth=False))

    assert above < H / 2 < below, (
        f"XR +Y landed at row {above:.0f} and -Y at row {below:.0f}: the image is upside down"
    )


def test_the_image_is_not_mirrored(rendered):
    """Horizontal, checked alongside the flip: mirroring one axis and not the
    other is what a mistaken second flip looks like."""
    render, read = rendered
    render([BOX_OFFSET, 0.0, -BOX_DISTANCE])
    _, right = _drawn_centre(read(0, is_depth=False))
    render([-BOX_OFFSET, 0.0, -BOX_DISTANCE])
    _, left = _drawn_centre(read(0, is_depth=False))

    assert left < W / 2 < right, (
        f"XR +X landed at column {right:.0f} and -X at {left:.0f}: the image is mirrored"
    )


def test_depth_is_the_standard_z_projection_layer_is_promised(rendered):
    """near -> 0, far -> 1, and the background is far.

    Getting it backwards leaves colour perfect and reprojection inverted, so the
    values are checked against the geometry, not merely for being in range.
    """
    render, read = rendered
    render([0.0, 0.0, -BOX_DISTANCE])
    depth = read(0, is_depth=True)
    color = read(0, is_depth=False)
    drawn = color[..., 3] > 0

    background = np.unique(depth[~drawn])
    assert background == pytest.approx([1.0]), (
        f"background depth {background}, expected exactly 1.0 (far). MuJoCo clears its "
        "reverse-Z buffer to 0, so anything else means the inversion is missing."
    )

    # The box's front face is flat and square to the eye, so every drawn pixel carries
    # one depth -- the FACE's, half a box nearer than the body's origin. Pinning that
    # exact value is what an in-range check would not do.
    expected = frames.submitted_depth(BOX_DISTANCE - BOX_HALF_SIZE, NEAR_Z, FAR_Z)
    assert depth[drawn] == pytest.approx(expected, abs=1e-4), (
        f"drawn depth spans [{depth[drawn].min():.4f}, {depth[drawn].max():.4f}], "
        f"expected {expected:.4f} for a face at {BOX_DISTANCE - BOX_HALF_SIZE} m"
    )


def test_the_eyes_see_the_object_at_different_offsets(rendered):
    """Stereo parallax and its sign: an object ahead sits further left in the
    RIGHT eye, and swapping the views reads as eye strain rather than as a bug."""
    render, read = rendered
    render([0.0, 0.0, -BOX_DISTANCE], eye_separation=0.032)
    _, left_eye = _drawn_centre(read(0, is_depth=False))
    _, right_eye = _drawn_centre(read(1, is_depth=False))

    assert right_eye < left_eye, (
        f"left eye sees the object at column {left_eye:.0f} and the right eye at "
        f"{right_eye:.0f}: the views are swapped"
    )
