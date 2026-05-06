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
- Color conversion auto-selects between BT.709 limited-range (default for
  general H.264 files: x264, ffmpeg, broadcast, streaming) and BT.601
  full-range (typical of embedded camera encoders that tag
  `video_full_range_flag=1`) using the H.264 VUI on the first frame.
  Mistagged sources will look wrong; pass `force_full_range` if added later.
- No audio.
- Single-threaded decode + render. NVDEC is async on the GPU but the decode
  call blocks the render loop briefly per frame.
