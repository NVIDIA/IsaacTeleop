#!/usr/bin/env python3
"""RTP H.264 video receiver with GStreamer and GTK display."""

import argparse
import signal
import time
import gi

gi.require_version('Gst', '1.0')
gi.require_version('Gtk', '3.0')
from gi.repository import Gst, GLib, Gtk


# Configuration constants
WINDOW_TITLE = "Isaac Teleop Streamer"
WINDOW_WIDTH = 1920
WINDOW_HEIGHT = 1080
STREAM_TIMEOUT_SEC = 3
STARTUP_GRACE_PERIOD_SEC = 3
STATUS_CHECK_INTERVAL_SEC = 10
UI_UPDATE_INTERVAL_SEC = 1
FRAME_LOG_INTERVAL = 150


class GStreamerReceiver:
    """RTP H.264 receiver with real-time GTK display and stream monitoring."""
    
    def __init__(self, port: int, use_hw_decode: bool = False):
        Gst.init(None)
        Gtk.init(None)
        
        self.last_frame_time = None
        self.frame_count = 0
        self.startup_time = time.time()
        
        self.pipeline = self._build_pipeline(port, use_hw_decode)
        self.window = self._create_window()
        
        self.pipeline.set_state(Gst.State.PLAYING)
        self._print_startup_info(port, use_hw_decode)
    
    def _build_pipeline(self, port: int, use_hw_decode: bool) -> Gst.Pipeline:
        """Build GStreamer pipeline with specified decoder."""
        if use_hw_decode:
            decoder = "nvh264dec max-display-delay=0 num-output-surfaces=1"
            caps_filter = "video/x-raw,format=NV12 ! "
        else:
            decoder = "avdec_h264"
            caps_filter = ""
        
        pipeline_desc = (
            f"udpsrc port={port} buffer-size=212992 "
            f"caps=\"application/x-rtp, media=video, encoding-name=H264, payload=96\" ! "
            f"rtpjitterbuffer latency=0 drop-on-latency=true do-retransmission=false ! "
            f"rtph264depay ! "
            f"h264parse config-interval=-1 ! "
            f"{decoder} ! "
            f"{caps_filter}"
            f"videoconvert ! "
            f"gtksink name=sink sync=false force-aspect-ratio=true"
        )
        
        pipeline = Gst.parse_launch(pipeline_desc)
        
        bus = pipeline.get_bus()
        bus.add_signal_watch()
        bus.connect("message", self._on_bus_message)
        
        gtksink = pipeline.get_by_name("sink")
        sink_pad = gtksink.get_static_pad("sink")
        sink_pad.add_probe(Gst.PadProbeType.BUFFER, self._on_frame_probe)
        
        return pipeline
    
    def _create_window(self) -> Gtk.Window:
        """Create GTK window with video widget and status overlay."""
        window = Gtk.Window()
        window.set_title(WINDOW_TITLE)
        window.set_default_size(WINDOW_WIDTH, WINDOW_HEIGHT)
        window.connect("delete-event", self._on_window_close)
        
        overlay = Gtk.Overlay()
        
        gtksink = self.pipeline.get_by_name("sink")
        video_widget = gtksink.get_property("widget")
        overlay.add(video_widget)
        
        self.status_label = self._create_status_label()
        overlay.add_overlay(self.status_label)
        
        window.add(overlay)
        window.show_all()
        
        GLib.timeout_add_seconds(STATUS_CHECK_INTERVAL_SEC, self._check_stream_status)
        GLib.timeout_add_seconds(UI_UPDATE_INTERVAL_SEC, self._update_ui_status)
        
        return window
    
    def _create_status_label(self) -> Gtk.Label:
        """Create centered status label for stream unavailable message."""
        label = Gtk.Label()
        label.set_markup(
            '<span font="32" weight="bold" foreground="#76B900" background="black">'
            '  VIDEO STREAM UNAVAILABLE  </span>'
        )
        label.set_halign(Gtk.Align.CENTER)
        label.set_valign(Gtk.Align.CENTER)
        label.set_no_show_all(True)
        return label
    
    def _is_stream_active(self) -> bool:
        """Check if stream has received frames recently."""
        if self.last_frame_time is None:
            return False
        return (time.time() - self.last_frame_time) <= STREAM_TIMEOUT_SEC
    
    def _on_frame_probe(self, pad, info):
        """GStreamer pad probe callback on each frame."""
        self.last_frame_time = time.time()
        self.frame_count += 1
        
        return Gst.PadProbeReturn.OK
    
    def _check_stream_status(self):
        """Periodic logging of stream status."""
        timestamp = time.strftime('%H:%M:%S')
        if not self._is_stream_active():
            print(f"[{timestamp}] No video stream available - waiting for stream on port...")
        elif self.frame_count % FRAME_LOG_INTERVAL == 0 and self.frame_count > 0:
            print(f"[{timestamp}] Streaming active - {self.frame_count} frames received")
        return True
    
    def _update_ui_status(self):
        """Update UI status message visibility."""
        time_since_startup = time.time() - self.startup_time
        
        if self._is_stream_active():
            self.status_label.hide()
        elif time_since_startup > STARTUP_GRACE_PERIOD_SEC:
            self.status_label.show()
        return True
    
    def _on_bus_message(self, bus, message):
        """Handle GStreamer bus messages."""
        msg_type = message.type
        if msg_type == Gst.MessageType.EOS:
            print("End-of-stream")
            self.stop()
        elif msg_type == Gst.MessageType.ERROR:
            err, debug = message.parse_error()
            print(f"Error: {err}, {debug}")
            self.stop()
    
    def _on_window_close(self, widget, event):
        """Handle window close event."""
        self.stop()
        return False
    
    def _print_startup_info(self, port: int, use_hw_decode: bool):
        """Print startup information."""
        decoder = "nvh264dec (hardware)" if use_hw_decode else "avdec_h264 (software)"
        print(f"GStreamer receiver listening on port {port}")
        print(f"Using decoder: {decoder}")
        print("Press Ctrl+C or close window to quit")
    
    def stop(self):
        """Stop pipeline and quit GTK main loop."""
        if self.pipeline:
            self.pipeline.set_state(Gst.State.NULL)
        Gtk.main_quit()


def main():
    parser = argparse.ArgumentParser(description="RTP H.264 receiver and viewer")
    parser.add_argument("--port", type=int, default=5000, help="UDP port to listen on")
    parser.add_argument("--hw", action="store_true", help="Use hardware H.264 decoder (nvh264dec)")
    args = parser.parse_args()
    
    print("Starting RTP H.264 receiver...")
    receiver = GStreamerReceiver(args.port, args.hw)
    print(f"Listening for RTP stream on port {args.port}")
    
    def signal_handler(sig, frame):
        print("\nInterrupted by user")
        receiver.stop()
    
    signal.signal(signal.SIGINT, signal_handler)
    
    try:
        Gtk.main()
    except Exception as e:
        print(f"Error: {e}")
    finally:
        receiver.stop()
        print("Cleanup complete")


if __name__ == "__main__":
    main()
