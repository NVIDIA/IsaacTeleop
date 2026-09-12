# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""
Visualize live raw hand fingertip poses in real time with viser.

Polls the "manus_sensors_left" / "manus_sensors_right" tensor collections pushed by the
manus plugin and draws each tracked tip as a labelled coordinate frame. Each collection
carries exactly one hand, so a stream's side comes from which collection it is.

Standalone: this reads JointSe3PoseTracker directly rather than going through the
retargeting engine, so it needs no source node. Open the URL viser prints to watch the
tips move; touch thumb to a fingertip and the two frames should meet.

Prerequisites (separate terminals):
  1. CloudXR runtime:  python -m isaacteleop.cloudxr
  2. the pusher:       ./install/plugins/manus/manus_hand_plugin --datasets=sensors

Usage:
    source ~/.cloudxr/run/cloudxr.env
    uv run live_joint_se3_pose.py [--collections a,b] [--port 8080]

Press Ctrl+C to stop.
"""

import argparse
import sys
import time

import viser

from isaacteleop.deviceio_session import DeviceIOSession
from isaacteleop.deviceio_trackers import JointSe3PoseTracker
from isaacteleop.oxr import OpenXRSession
from isaacteleop.schema import JointName

DEFAULT_COLLECTIONS = ["manus_sensors_left", "manus_sensors_right"]

# Tip label -> JointName, thumb first so the pinch partner is easy to spot.
TIPS = [
    ("thumb", JointName.HAND_RAW_THUMB_TIP),
    ("index", JointName.HAND_RAW_INDEX_TIP),
    ("middle", JointName.HAND_RAW_MIDDLE_TIP),
    ("ring", JointName.HAND_RAW_RING_TIP),
    ("little", JointName.HAND_RAW_LITTLE_TIP),
]


class TipViz:
    """One labelled coordinate frame per fingertip, for a single collection."""

    def __init__(self, server: viser.ViserServer, collection_id: str):
        self._frames = {}
        for label, joint in TIPS:
            self._frames[joint] = server.scene.add_frame(
                f"/{collection_id}/{label}",
                axes_length=0.02,
                axes_radius=0.002,
                visible=False,
            )
            server.scene.add_label(f"/{collection_id}/{label}/label", text=label)

    def update(self, data) -> None:
        for _, joint in TIPS:
            frame = self._frames[joint]
            found = data.lookup(joint) if data is not None else None
            if found is None:
                # Absent from the frame means untracked; there is no validity flag.
                frame.visible = False
                continue
            p, q = found.pose.position, found.pose.orientation
            frame.position = (p.x, p.y, p.z)
            # schema quaternion is (x, y, z, w); viser expects (w, x, y, z).
            frame.wxyz = (q.w, q.x, q.y, q.z)
            frame.visible = True


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--collections",
        default=",".join(DEFAULT_COLLECTIONS),
        help=f"Comma-separated collection ids (default: {','.join(DEFAULT_COLLECTIONS)})",
    )
    parser.add_argument(
        "--host",
        default="0.0.0.0",
        help="Viser HTTP bind address (default: 0.0.0.0, all interfaces; pass 127.0.0.1 to keep it local)",
    )
    parser.add_argument("--port", type=int, default=8080, help="Viser HTTP port")
    args = parser.parse_args(argv[1:])

    collections = [c.strip() for c in args.collections.split(",") if c.strip()]
    if not collections:
        print("[live-joints] no collections given", file=sys.stderr)
        return 1

    server = viser.ViserServer(host=args.host, port=args.port)
    server.scene.set_up_direction("+y")
    server.scene.add_grid(name="/grid", width=0.5, height=0.5, cell_size=0.05)
    viz = {cid: TipViz(server, cid) for cid in collections}
    print(
        f"[live-joints] viser listening on {args.host}:{args.port} "
        f"(http://localhost:{args.port})"
    )

    trackers = {cid: JointSe3PoseTracker(cid) for cid in collections}
    tracker_list = list(trackers.values())
    extensions = DeviceIOSession.get_required_extensions(tracker_list)
    with OpenXRSession("LiveJointSe3Pose", extensions) as oxr_session:
        with DeviceIOSession.run(tracker_list, oxr_session.get_handles()) as session:
            print("[live-joints] streaming — Ctrl+C to stop")
            try:
                while True:
                    session.update()
                    for cid, tracker in trackers.items():
                        viz[cid].update(tracker.get_data(session).data)
                    time.sleep(1 / 90)
            except KeyboardInterrupt:
                pass

    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
