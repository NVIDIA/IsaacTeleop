#!/usr/bin/env python3
"""Standalone OAK-D camera with H.264 encoding and RTP streaming."""

import argparse
import time
import depthai as dai
import gi

gi.require_version('Gst', '1.0')
from gi.repository import Gst


class GStreamerStreamer:
    """Simple GStreamer RTP H.264 streamer."""
    
    def __init__(self, host: str, port: int):
        Gst.init(None)
        
        pipeline_desc = (
            f"appsrc name=src is-live=true do-timestamp=true format=time "
            f"caps=video/x-h264,stream-format=byte-stream,alignment=au ! "
            f"h264parse config-interval=1 ! "
            f"rtph264pay pt=96 mtu=1400 config-interval=1 ! "
            f"udpsink host={host} port={port} sync=false async=false"
        )
        
        self.pipeline = Gst.parse_launch(pipeline_desc)
        self.appsrc = self.pipeline.get_by_name('src')
        self.pipeline.set_state(Gst.State.PLAYING)
        
        print(f"GStreamer RTP streaming to {host}:{port}")
    
    def send_h264(self, data: bytes):
        """Send H.264 data to GStreamer pipeline."""
        if not data or len(data) == 0:
            return
        buf = Gst.Buffer.new_wrapped(data)
        self.appsrc.emit('push-buffer', buf)
    
    def stop(self):
        """Stop GStreamer pipeline."""
        if self.pipeline:
            self.pipeline.set_state(Gst.State.NULL)


def create_camera_pipeline(args):
    """Create and configure OAK-D camera pipeline."""
    pipeline = dai.Pipeline()
    
    cam = pipeline.create(dai.node.Camera).build(dai.CameraBoardSocket.CAM_A)
    
    encode_output = cam.requestOutput(
        (args.width, args.height),
        type=dai.ImgFrame.Type.NV12,
        fps=args.fps
    )
    
    encoder = pipeline.create(dai.node.VideoEncoder).build(
        encode_output,
        frameRate=args.fps,
        profile=dai.VideoEncoderProperties.Profile.H264_BASELINE,
        bitrate=args.bitrate,
        quality=args.quality
    )
    
    try:
        encoder.setNumFramesPool(3)
        encoder.setRateControlMode(dai.VideoEncoderProperties.RateControlMode.CBR)
        encoder.setKeyframeFrequency(15)
        encoder.setNumBFrames(0)
    except Exception as e:
        print(f"Note: Some encoder settings not available: {e}")
    
    h264_queue = encoder.out.createOutputQueue(maxSize=6, blocking=False)
    
    return pipeline, h264_queue


def main():
    parser = argparse.ArgumentParser(description="OAK-D camera with H.264 RTP streaming")
    parser.add_argument("--width", type=int, default=1280, help="Frame width")
    parser.add_argument("--height", type=int, default=720, help="Frame height")
    parser.add_argument("--fps", type=int, default=50, help="Frame rate")
    parser.add_argument("--bitrate", type=int, default=20_000_000, help="H.264 bitrate (bps)")
    parser.add_argument("--quality", type=int, default=80, help="H.264 quality (1-100, higher=better)")
    parser.add_argument("--stream-host", type=str, default="127.0.0.1", help="RTP destination host")
    parser.add_argument("--stream-port", type=int, default=5000, help="RTP destination port")
    parser.add_argument("--retry-interval", type=int, default=10, help="Camera retry interval (seconds)")
    args = parser.parse_args()
    
    print(f"DepthAI version: {dai.__version__}")
    print(f"Configuration: {args.width}x{args.height} @ {args.fps}fps, {args.bitrate/1_000_000:.1f}Mbps")
    
    # Initialize GStreamer streamer (persists across camera reconnections)
    streamer = GStreamerStreamer(args.stream_host, args.stream_port)
    print(f"Streaming to {args.stream_host}:{args.stream_port}")
    print("Press Ctrl+C to quit")
    
    pipeline = None
    h264_queue = None
    
    try:
        while True:
            retry_count = 0
            
            # Camera initialization/reconnection loop
            while True:
                try:
                    if pipeline:
                        pipeline.stop()
                    pipeline, h264_queue = create_camera_pipeline(args)
                    pipeline.start()
                    print("Camera and encoder started")
                    break
                except Exception as e:
                    retry_count += 1
                    print(f"Failed to initialize camera (attempt {retry_count}): {e}")
                    print(f"Retrying in {args.retry_interval} seconds...")
                    try:
                        time.sleep(args.retry_interval)
                    except KeyboardInterrupt:
                        print("\nInterrupted by user during retry wait")
                        raise
            
            # Main streaming loop
            try:
                while pipeline.isRunning():
                    pipeline.processTasks()
                    
                    if h264_queue.has():
                        encoded_msg = h264_queue.get()
                        if isinstance(encoded_msg, dai.EncodedFrame):
                            h264_data = bytes(encoded_msg.getData())
                            if h264_data:
                                streamer.send_h264(h264_data)
                
                # Pipeline stopped unexpectedly - attempt reconnection
                print("Camera stream stopped unexpectedly. Attempting to reconnect...")
                
            except Exception as e:
                print(f"Streaming error: {e}. Attempting to reconnect...")
                    
    except KeyboardInterrupt:
        print("\nInterrupted by user")
    finally:
        if pipeline:
            pipeline.stop()
        streamer.stop()
        print("Cleanup complete")


if __name__ == "__main__":
    main()

