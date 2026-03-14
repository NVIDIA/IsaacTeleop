#!/usr/bin/env python3
# SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
# http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""
Mock Haply SDK WebSocket server for integration testing.

Emulates the Haply Inverse Service by streaming synthetic Inverse3 and
VerseGrip device data over WebSocket at ws://localhost:<port>.

Usage:
    python3 mock_haply_server.py [--port PORT] [--hz HZ] [--handedness left|right] [--duration SECONDS]

The server sends JSON messages matching the Haply SDK wire format and
accepts force commands back. Device positions follow a Lissajous curve,
orientation rotates smoothly, and buttons cycle on/off periodically.

Useful for:
    - Integration testing HaplyHandTrackerPrinter without hardware
    - Developing against the Haply plugin locally
    - CI smoke tests
"""

import argparse
import asyncio
import json
import math
import signal
import sys
import time

try:
    import websockets
    import websockets.server
except ImportError:
    print("Error: 'websockets' package required. Install with: pip install websockets", file=sys.stderr)
    sys.exit(1)


class MockHaplyDevice:
    """Generates synthetic Haply device data."""

    def __init__(self, handedness: str = "right"):
        self.handedness = handedness
        self.inverse3_device_id = "mock-inverse3-001"
        self.versegrip_device_id = "mock-versegrip-001"
        self.start_time = time.monotonic()
        self.frame_count = 0
        self.last_force = {"x": 0.0, "y": 0.0, "z": 0.0}

    def get_state(self, first_message: bool = False) -> dict:
        """Generate a single frame of mock device data."""
        t = time.monotonic() - self.start_time
        self.frame_count += 1

        # Lissajous curve for position (bounded workspace ~[-0.1, 0.1] meters)
        amplitude = 0.08
        px = amplitude * math.sin(2.0 * math.pi * 0.3 * t)
        py = amplitude * math.sin(2.0 * math.pi * 0.5 * t + math.pi / 4.0)
        pz = 0.15 + amplitude * 0.5 * math.sin(2.0 * math.pi * 0.2 * t)  # centered ~15cm up

        # Velocity (numerical derivative approximation)
        dt = 0.005  # 200Hz
        vx = amplitude * 2.0 * math.pi * 0.3 * math.cos(2.0 * math.pi * 0.3 * t)
        vy = amplitude * 2.0 * math.pi * 0.5 * math.cos(2.0 * math.pi * 0.5 * t + math.pi / 4.0)
        vz = amplitude * 0.5 * 2.0 * math.pi * 0.2 * math.cos(2.0 * math.pi * 0.2 * t)

        # Smooth quaternion rotation around Y axis
        angle = 0.5 * math.sin(2.0 * math.pi * 0.1 * t)  # gentle oscillation
        qw = math.cos(angle / 2.0)
        qx = 0.0
        qy = math.sin(angle / 2.0)
        qz = 0.0

        # Buttons: cycle through patterns every 3 seconds
        button_phase = int(t / 3.0) % 4
        buttons = {
            "0": button_phase == 0 or button_phase == 3,
            "1": button_phase == 1 or button_phase == 3,
            "2": button_phase == 2,
            "3": button_phase == 3,
        }

        # Build Inverse3 device data
        inverse3_data = {
            "device_id": self.inverse3_device_id,
            "state": {
                "cursor_position": {"x": round(px, 6), "y": round(py, 6), "z": round(pz, 6)},
                "cursor_velocity": {"x": round(vx, 6), "y": round(vy, 6), "z": round(vz, 6)},
            },
        }

        # Include config only in first message
        if first_message:
            inverse3_data["config"] = {"handedness": self.handedness}

        # Build VerseGrip device data
        versegrip_data = {
            "device_id": self.versegrip_device_id,
            "state": {
                "buttons": buttons,
                "orientation": {
                    "w": round(qw, 6),
                    "x": round(qx, 6),
                    "y": round(qy, 6),
                    "z": round(qz, 6),
                },
            },
        }

        if first_message:
            versegrip_data["config"] = {}

        return {
            "inverse3": [inverse3_data],
            "wireless_verse_grip": [versegrip_data],
        }

    def process_command(self, msg: dict):
        """Process incoming force commands."""
        inverse3_cmds = msg.get("inverse3", [])
        for cmd in inverse3_cmds:
            force_cmd = cmd.get("commands", {}).get("set_cursor_force", {})
            values = force_cmd.get("values", {})
            if values:
                self.last_force = {
                    "x": values.get("x", 0.0),
                    "y": values.get("y", 0.0),
                    "z": values.get("z", 0.0),
                }


async def handle_client(websocket, device: MockHaplyDevice, hz: float, verbose: bool):
    """Handle a single WebSocket client connection."""
    period = 1.0 / hz
    first_message = True
    client_addr = websocket.remote_address

    print(f"[mock-haply] Client connected: {client_addr}")

    try:
        while True:
            # Send device state
            state = device.get_state(first_message=first_message)
            first_message = False
            await websocket.send(json.dumps(state))

            if verbose and device.frame_count % int(hz) == 0:
                pos = state["inverse3"][0]["state"]["cursor_position"]
                print(
                    f"[mock-haply] frame={device.frame_count} "
                    f"pos=({pos['x']:.3f}, {pos['y']:.3f}, {pos['z']:.3f}) "
                    f"force=({device.last_force['x']:.3f}, {device.last_force['y']:.3f}, {device.last_force['z']:.3f})"
                )

            # Try to receive a force command (non-blocking with short timeout)
            try:
                raw = await asyncio.wait_for(websocket.recv(), timeout=period * 0.8)
                try:
                    cmd = json.loads(raw)
                    device.process_command(cmd)
                except json.JSONDecodeError:
                    pass
            except asyncio.TimeoutError:
                pass

            # Maintain target frequency
            await asyncio.sleep(period * 0.2)

    except websockets.exceptions.ConnectionClosed:
        print(f"[mock-haply] Client disconnected: {client_addr}")
    except Exception as e:
        print(f"[mock-haply] Error with client {client_addr}: {e}")


async def run_server(port: int, hz: float, handedness: str, duration: float, verbose: bool):
    """Run the mock Haply WebSocket server."""
    device = MockHaplyDevice(handedness=handedness)

    print(f"[mock-haply] Starting mock Haply SDK server")
    print(f"[mock-haply]   WebSocket: ws://localhost:{port}")
    print(f"[mock-haply]   Frequency: {hz} Hz")
    print(f"[mock-haply]   Handedness: {handedness}")
    print(f"[mock-haply]   Duration: {'infinite' if duration <= 0 else f'{duration}s'}")
    print(f"[mock-haply] Waiting for connections...")

    stop_event = asyncio.Event()

    # Handle shutdown signals
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, stop_event.set)

    async with websockets.serve(
        lambda ws: handle_client(ws, device, hz, verbose),
        "localhost",
        port,
    ):
        if duration > 0:
            try:
                await asyncio.wait_for(stop_event.wait(), timeout=duration)
            except asyncio.TimeoutError:
                pass
            print(f"\n[mock-haply] Duration elapsed ({duration}s). Shutting down.")
        else:
            await stop_event.wait()
            print(f"\n[mock-haply] Shutting down.")

    print(f"[mock-haply] Total frames sent: {device.frame_count}")


def main():
    parser = argparse.ArgumentParser(
        description="Mock Haply SDK WebSocket server for integration testing",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
    # Run at default 200Hz on port 10001
    python3 mock_haply_server.py

    # Run for 10 seconds then exit (useful for CI)
    python3 mock_haply_server.py --duration 10

    # Run left-handed at 100Hz with verbose output
    python3 mock_haply_server.py --handedness left --hz 100 --verbose

    # Use a different port
    python3 mock_haply_server.py --port 10002
""",
    )
    parser.add_argument("--port", type=int, default=10001, help="WebSocket port (default: 10001)")
    parser.add_argument("--hz", type=float, default=200.0, help="Update frequency in Hz (default: 200)")
    parser.add_argument(
        "--handedness", choices=["left", "right"], default="right", help="Device handedness (default: right)"
    )
    parser.add_argument(
        "--duration",
        type=float,
        default=0,
        help="Run for N seconds then exit. 0 = run forever (default: 0)",
    )
    parser.add_argument("--verbose", "-v", action="store_true", help="Print periodic status updates")

    args = parser.parse_args()
    asyncio.run(run_server(args.port, args.hz, args.handedness, args.duration, args.verbose))


if __name__ == "__main__":
    main()
