# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""The viser panel.

The only module in this package that imports viser, which is an optional extra. The
status list shows the *final* result of every check and never a partial one: three
checks need the whole recording by construction (the validity trend compares a head
window against a tail window, cumulative drift needs both T-poses, and all of G4 needs
the labels), so a ``result()`` taken mid-playback would be a number with no meaning.
"""

from __future__ import annotations

import time

import numpy as np
import viser
from viser import uplot

from ..frames import NUM_JOINTS
from ..report import Mark, Report
from . import render, status
from .track import Sample, Track

LIVE_JOINT_COLOUR = (86, 196, 138)
HELD_JOINT_COLOUR = (214, 74, 62)
BONE_COLOUR = (150, 158, 172)

RATE_WINDOW_S = 8.0
PLOT_PERIOD_S = 0.2
TICK_S = 1.0 / 60.0
SPEEDS = {"0.25x": 0.25, "0.5x": 0.5, "1x": 1.0, "2x": 2.0, "4x": 4.0}


class Skeleton:
    """Joint cloud, bones, and a name floating beside every joint that is not live."""

    def __init__(self, server: viser.ViserServer, track: Track) -> None:
        self._names = track.profile.joint_names
        self._bones = track.profile.bones()
        self._points = server.scene.add_point_cloud(
            "/body/joints",
            points=np.zeros((0, 3), np.float32),
            colors=np.zeros((0, 3), np.uint8),
            point_size=0.022,
            point_shape="circle",
        )
        self._lines = server.scene.add_line_segments(
            "/body/bones",
            points=np.zeros((0, 2, 3), np.float32),
            colors=np.zeros((0, 2, 3), np.uint8),
            thickness=2.5,
            thickness_units="screen",
        )
        self._labels = [
            server.scene.add_label(f"/body/name/{name}", name, visible=False)
            for name in self._names
        ]
        self._named: set[int] = set()

    def draw(self, sample: Sample, name_held: bool) -> None:
        points: list[tuple[float, float, float]] = []
        colours: list[tuple[int, int, int]] = []
        for index, position in enumerate(sample.positions):
            if position is None:
                continue
            points.append(position)
            colours.append(
                LIVE_JOINT_COLOUR if sample.valid[index] else HELD_JOINT_COLOUR
            )
        self._points.points = np.asarray(points, np.float32).reshape(-1, 3)
        self._points.colors = np.asarray(colours, np.uint8).reshape(-1, 3)

        segments: list[tuple] = []
        segment_colours: list[tuple] = []
        for parent, child in self._bones:
            start, end = sample.positions[parent], sample.positions[child]
            if start is None or end is None:
                continue
            live = sample.valid[parent] and sample.valid[child]
            colour = BONE_COLOUR if live else HELD_JOINT_COLOUR
            segments.append((start, end))
            segment_colours.append((colour, colour))
        self._lines.points = np.asarray(segments, np.float32).reshape(-1, 2, 3)
        self._lines.colors = np.asarray(segment_colours, np.uint8).reshape(-1, 2, 3)

        wanted = (
            {
                index
                for index, position in enumerate(sample.positions)
                if position is not None and not sample.valid[index]
            }
            if name_held
            else set()
        )
        for index in wanted:
            position = sample.positions[index]
            assert position is not None
            self._labels[index].position = position
        for index in wanted - self._named:
            self._labels[index].visible = True
        for index in self._named - wanted:
            self._labels[index].visible = False
        self._named = wanted

    def held_names(self, sample: Sample) -> list[str]:
        return [
            self._names[index]
            for index, position in enumerate(sample.positions)
            if position is not None and not sample.valid[index]
        ]


class Panel:
    def __init__(self, server: viser.ViserServer, report: Report, track: Track) -> None:
        self._server = server
        self._report = report
        self._track = track
        self._playhead_s = 0.0
        self._index = 0

        # The mark colours in `render` are chosen against a light background.
        server.gui.configure_theme(control_width="large", dark_mode=False)
        server.scene.set_up_direction("+y")
        server.scene.add_grid(
            "/floor", width=3.0, height=3.0, plane="xz", cell_size=0.25
        )
        server.scene.add_frame("/origin", axes_length=0.3, axes_radius=0.004)
        server.initial_camera.position = (2.2, 1.6, 2.6)
        server.initial_camera.look_at = (0.0, 0.9, 0.0)
        self._skeleton = Skeleton(server, track)

        self._build_gui()
        self._seek(0)

    def _build_gui(self) -> None:
        gui = self._server.gui
        report, track = self._report, self._track

        gui.add_html(render.verdict_banner(report))
        gui.add_html(
            render.facts(
                (
                    ("recording", report.source.rsplit("/", 1)[-1]),
                    ("frames", f"{report.frames}"),
                    ("duration", f"{track.duration_s:.1f} s"),
                    ("clock", track.clock or "-"),
                    ("joints valid", f"at worst {track.min_valid_count}/{NUM_JOINTS}"),
                    ("topic", report.metadata.topic or "-"),
                )
            )
        )
        for note in report.notes:
            gui.add_html(f'<div style="font-size:11px;opacity:0.7">note: {note}</div>')

        with gui.add_folder("Playback"):
            self._scrub = gui.add_slider(
                "frame",
                min=0,
                max=max(len(track.samples) - 1, 0),
                step=1,
                initial_value=0,
            )
            self._playing = gui.add_checkbox("play", initial_value=False)
            self._speed = gui.add_dropdown("speed", tuple(SPEEDS), initial_value="1x")
            self._name_held = gui.add_checkbox("name held joints", initial_value=True)
            self._readout = gui.add_html("")

            @self._scrub.on_update
            def _(_: viser.GuiEvent) -> None:
                self._seek(int(self._scrub.value))

        with gui.add_folder("Decides the take"):
            gui.add_html(render.result_rows(status.decisive(report)))
            low, high = track.rate_extent() or (0.0, 1.0)
            pad = max(0.5, (high - low) * 0.1)
            self._rate_plot = gui.add_uplot(
                data=(np.zeros(1), np.zeros(1), np.zeros(1)),
                series=(
                    uplot.Series(label="s"),
                    uplot.Series(label="Hz", stroke="#2b7de0", width=1.5),
                    uplot.Series(label="median", stroke="#9aa3ad", width=1.0),
                ),
                # Spanning the whole take, so the axis does not move under the curve
                # while it scrolls and a dropped frame stays a step rather than a
                # rescale. See Track.rate_extent for the other reason it is fixed.
                scales={
                    "x": uplot.Scale(time=False),
                    "y": uplot.Scale(min=low - pad, max=high + pad),
                },
                title=f"frame rate, last {RATE_WINDOW_S:.0f} s",
                height=110,
            )
            validity_t, validity_count = track.validity_series()
            gui.add_uplot(
                data=(
                    np.asarray(validity_t or [0.0]),
                    np.asarray(validity_count or [0.0]),
                ),
                series=(
                    uplot.Series(label="s"),
                    uplot.Series(label="valid joints", stroke="#b0342c", width=1.5),
                ),
                scales={
                    "x": uplot.Scale(time=False),
                    "y": uplot.Scale(min=0.0, max=float(NUM_JOINTS)),
                },
                title="valid joints, whole take",
                height=110,
            )

        for gate in status.gates(report):
            with gui.add_folder(
                render.gate_heading(gate),
                expand_by_default=gate.mark not in (None, Mark.PASS),
            ):
                gui.add_html(render.gate_body(gate))

    def _seek(self, index: int) -> None:
        samples = self._track.samples
        if not samples:
            return
        self._index = max(0, min(index, len(samples) - 1))
        self._playhead_s = samples[self._index].t_s
        self._draw()

    def _draw(self) -> None:
        samples = self._track.samples
        if not samples:
            return
        sample = samples[self._index]
        with self._server.atomic():
            self._skeleton.draw(sample, self._name_held.value)
            self._readout.content = render.playhead(
                t_s=sample.t_s,
                duration_s=self._track.duration_s,
                sequence=sample.sequence,
                valid_count=sample.valid_count,
                total_joints=NUM_JOINTS,
                step=sample.step,
                held=self._skeleton.held_names(sample),
            )

    def draw_rate(self) -> None:
        times, rates = self._track.rate_window(self._index, RATE_WINDOW_S)
        finite = [rate for rate in rates if rate == rate]
        if not finite:
            return
        self._rate_plot.data = (
            np.asarray(times),
            np.asarray(rates),
            np.full(len(times), float(np.median(finite))),
        )

    def advance(self, elapsed_s: float) -> None:
        """One playback tick, wall-clock driven so the take plays at its own rate."""
        if not (self._playing.value and self._track.samples):
            return
        self._playhead_s += elapsed_s * SPEEDS[self._speed.value]
        if self._playhead_s > self._track.duration_s:
            self._playhead_s = 0.0
        index = self._track.index_at(self._playhead_s)
        if index != self._index:
            self._index = index
            self._scrub.value = index
            self._draw()

    def run(self) -> None:
        last = time.monotonic()
        plotted = 0.0
        while True:
            now = time.monotonic()
            elapsed, last = now - last, now
            self.advance(elapsed)
            if now - plotted > PLOT_PERIOD_S:
                plotted = now
                self.draw_rate()
            time.sleep(TICK_S)


def serve(
    report: Report, track: Track, host: str = "127.0.0.1", port: int = 8080
) -> None:
    server = viser.ViserServer(host=host, port=port)
    panel = Panel(server, report, track)
    print(f"[panel] http://{host}:{port} — Ctrl+C to stop")
    try:
        panel.run()
    except KeyboardInterrupt:
        pass
    finally:
        server.stop()
