# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
"""Network transports for camera_viz.

Transport modules wrap byte-stream I/O (RTP / UDP / TCP) and stay codec-
agnostic — the codec layer lives in ``sources/`` (decoders, which feed
into FrameSource) and in ``camera_send`` (encoders, which consume
FrameSource).

The split matches camera_streamer's gstreamer + nv_stream split: one
side handles network packetization, the other handles GPU codec work.
"""

from .rtp_h264_receiver import RtpH264Receiver
from .rtp_h264_sender import RtpH264Sender

__all__ = ["RtpH264Receiver", "RtpH264Sender"]
