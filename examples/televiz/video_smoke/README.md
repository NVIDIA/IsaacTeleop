# viz_video_smoke

Plays an H.264 video file into a Televiz `QuadLayer` via NVDEC. Standalone — no
Holoscan / HoloHub / GXF dependency. The decoded NV12 frame is converted to
RGBA8 by a single CUDA kernel and submitted as a `VizBuffer` to the layer's
mailbox.

## Build

The example is built when `BUILD_VIZ=ON` and `BUILD_EXAMPLES=ON`. It silently
skips at configure time if `libnvcuvid` is not on the system. The NVIDIA Video
Codec SDK is downloaded once at configure time (cached under
`build/_deps/nvc_sdk/`).

```sh
cmake -S . -B build -DBUILD_VIZ=ON -DBUILD_EXAMPLES=ON
cmake --build build --target viz_video_smoke -j
```

## Run

```sh
./build/examples/televiz/video_smoke/viz_video_smoke path/to/video.h264
# Or two (or more) side-by-side via row-major tiling:
./build/examples/televiz/video_smoke/viz_video_smoke a.h264 b.h264
```

The example expects a raw H.264 Annex B elementary stream. Convert from MP4 /
MKV with:

```sh
ffmpeg -i in.mp4 -c:v copy -bsf:v h264_mp4toannexb -f h264 out.h264
```

The video loops on EOF.

## What this exercises

- `VizSession(kWindow)` end-to-end: GLFW + Vulkan swapchain + render loop
- `QuadLayer` triple-buffer mailbox under a real producer (one decoded frame
  per render iteration)
- CUDA-Vulkan interop on the producer side (NVDEC → CUDA device pointer →
  Televiz `submit()` which `cudaMemcpyAsync`s into the layer slot)
- Frame pacer + monitor refresh detection

## Limitations

- H.264 only (NVDEC supports HEVC/AV1 too; would need codec selection).
- Color conversion is BT.709 limited-range only (NPP's
  `nppiNV12ToRGB_709CSC_8u_P2C3R` plus a tiny RGB→RGBA pack kernel).
  This is correct for ~all general-purpose H.264 (x264, ffmpeg,
  broadcast, streaming). Embedded camera encoders that emit BT.601
  full-range (OAK-D etc.) will look slightly washed out; the original
  `examples/camera_streamer/operators/nv_stream_decoder/` op auto-detects
  via the H.264 VUI flag.
- No audio.
- Single-threaded decode + render. NVDEC is async on the GPU but the decode
  call blocks the render loop briefly per frame.
