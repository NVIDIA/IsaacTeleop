# SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
"""
Teleop Camera Sender Subgraph.

Wraps the camera sender pipeline (camera sources -> encoders -> RTP senders)
as a reusable Holoscan Subgraph. Exposes raw frame output interface ports so
parent applications can tap camera frames for additional processing.

The RTP streaming is self-contained within the subgraph. The output ports are
an optional tap — if nothing connects to them, the sender works identically
to the standalone TeleopCameraSenderApp.
"""

from typing import Any

from camera_config import CameraConfig
from camera_sources import create_camera_source, ensure_nvenc_support
from holoscan.core import Fragment, Subgraph
from holoscan.resources import UnboundedAllocator
from loguru import logger
from operators.gstreamer_h264_sender.gstreamer_h264_sender_op import (
    GStreamerH264SenderOp,
)


class TeleopCameraSenderSubgraph(Subgraph):
    """Camera sender pipeline as a reusable Subgraph.

    Streams cameras over RTP and exposes raw frame output ports per camera
    for downstream consumers.

    Output ports (available after compose()):
        One output interface port per camera, named by camera name
        (e.g. "head", "left_wrist", "right_wrist").

        For stereo_rgb cameras: the RGB center frame.
        For stereo cameras: the left frame.
        For mono cameras: the mono frame.
    """

    def __init__(
        self,
        fragment: Fragment,
        name: str,
        *,
        cameras: dict[str, CameraConfig],
        host: str,
        cuda_device: int = 0,
        verbose: bool = False,
        force_raw: bool = False,
    ):
        self._cameras = cameras
        self._host = host
        self._cuda_device = cuda_device
        self._verbose = verbose
        self._force_raw = force_raw
        self._camera_output_names: list[str] = []
        super().__init__(fragment, name)

    @property
    def camera_output_names(self) -> list[str]:
        """Names of camera raw frame output interface ports (available after compose)."""
        return list(self._camera_output_names)

    def compose(self):
        verbose = self._verbose
        host = self._host
        cuda_device = self._cuda_device
        allocator = UnboundedAllocator(self.fragment, name=f"{self.name}_allocator")

        NvStreamEncoderOp = None
        needs_nvenc = self._force_raw or any(
            c.camera_type in ("zed", "v4l2", "video_file") or c.stereo
            for c in self._cameras.values()
        )
        if needs_nvenc:
            NvStreamEncoderOp = ensure_nvenc_support()

        raw_frame_outputs: dict[str, tuple[Any, str]] = {}

        for cam_name, cam_cfg in self._cameras.items():
            logger.info(f"Adding camera: {cam_name} ({cam_cfg.camera_type})")

            if self._force_raw:
                output_format = "raw"
            elif cam_cfg.camera_type == "oakd" and not cam_cfg.stereo:
                output_format = "h264"
            else:
                output_format = "raw"

            source_result = create_camera_source(
                self.fragment,
                cam_name,
                cam_cfg,
                allocator,
                output_format=output_format,
                verbose=verbose,
            )

            for op in source_result.operators:
                self.add_operator(op)
            for src_op, dst_op, port_map in source_result.flows:
                self.add_flow(src_op, dst_op, port_map)

            for stream_name, (src_op, src_port) in source_result.frame_outputs.items():
                stream_cfg = cam_cfg.streams.get(stream_name)

                # stereo_rgb: "rgb" stream goes to output port, not RTP
                if stream_name == "rgb":
                    raw_frame_outputs[cam_name] = (src_op, src_port)
                    continue

                if stream_cfg is None:
                    continue

                if output_format == "h264":
                    rtp_sender = GStreamerH264SenderOp(
                        self.fragment,
                        name=f"{cam_name}_{stream_name}_rtp",
                        host=host,
                        port=stream_cfg.port,
                        verbose=verbose,
                    )
                    self.add_flow(src_op, rtp_sender, {(src_port, "h264_packets")})
                    self.add_operator(rtp_sender)
                    # H.264 packets are not raw frames — don't expose to output ports.
                else:
                    encoder = NvStreamEncoderOp(
                        self.fragment,
                        name=f"{cam_name}_{stream_name}_encoder",
                        width=cam_cfg.width,
                        height=cam_cfg.height,
                        bitrate=stream_cfg.bitrate_bps,
                        fps=cam_cfg.fps,
                        cuda_device_ordinal=cuda_device,
                        input_format="bgra",
                        verbose=verbose,
                    )
                    rtp_sender = GStreamerH264SenderOp(
                        self.fragment,
                        name=f"{cam_name}_{stream_name}_rtp",
                        host=host,
                        port=stream_cfg.port,
                        verbose=verbose,
                    )
                    self.add_flow(src_op, encoder, {(src_port, "frame")})
                    self.add_flow(encoder, rtp_sender, {("packet", "h264_packets")})
                    self.add_operator(encoder)
                    self.add_operator(rtp_sender)

                    if cam_name not in raw_frame_outputs:
                        raw_frame_outputs[cam_name] = (src_op, src_port)

                logger.info(
                    f"  {stream_name}: {cam_cfg.width}x{cam_cfg.height}@{cam_cfg.fps}fps "
                    f"-> RTP {host}:{stream_cfg.port}"
                )

        for cam_name, (op, port) in raw_frame_outputs.items():
            self.add_output_interface_port(cam_name, op, port)
        self._camera_output_names = list(raw_frame_outputs.keys())

        logger.info(
            f"Sender subgraph: {len(self._cameras)} cameras, "
            f"output ports: {self._camera_output_names}"
        )
