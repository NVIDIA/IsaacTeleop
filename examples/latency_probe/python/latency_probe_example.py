# SPDX-FileCopyrightText: Copyright (c) 2025-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Bidirectional latency probe — generic vendor I/O teaching example.

Data flow::

    latency_probe plugin (LatencyProbeRequest)
            |
            v
    LatencyProbeSource -> InvertFloat -> DeviceOutputSink
            |
            v
    latency_probe plugin (LatencyProbeResponse, RTT stats every ~5s)

The host path uses :class:`DeviceOutputSink` and
:class:`~isaacteleop.device_output.SchemaPushOutputAdapter` — not the haptic
stack. See ``docs/source/device/add_device.rst`` (vendor output section).
"""

from __future__ import annotations

import argparse
import time
from pathlib import Path

import numpy as np

from isaacteleop.cloudxr import CloudXRLauncher
from isaacteleop.device_output import SchemaPushOutputAdapter
from isaacteleop.retargeting_engine.deviceio_source_nodes import (
    DeviceOutputSink,
    LatencyProbeSource,
)
from isaacteleop.retargeting_engine.deviceio_source_nodes.latency_probe_source import (
    PROBE_SEQUENCE_INDEX,
    PROBE_VALUE_INDEX,
)
from isaacteleop.retargeting_engine.interface import BaseRetargeter, OutputCombiner
from isaacteleop.retargeting_engine.interface.retargeter_core_types import (
    ComputeContext,
    RetargeterIO,
    RetargeterIOType,
)
from isaacteleop.retargeting_engine.interface.tensor_group_type import OptionalType
from isaacteleop.retargeting_engine.tensor_types.latency_probe_types import (
    LatencyProbeTensor,
)
from isaacteleop.schema import LatencyProbeResponse
from isaacteleop.teleop_session_manager import (
    PluginConfig,
    TeleopSession,
    TeleopSessionConfig,
)

APP_NAME = "LatencyProbeExample"
FPS = 60.0

IN_COLLECTION_ID = "latency_probe_in"
OUT_COLLECTION_ID = "latency_probe_out"
PLUGIN_ROOT_DIR = Path(__file__).resolve().parent.parent.parent.parent / "plugins"


class InvertFloat(BaseRetargeter):
    """Example retargeter: negate ``value``, pass ``sequence`` through."""

    INPUT_PROBE = "probe"
    OUTPUT_RESPONSE = "response"

    def input_spec(self) -> RetargeterIOType:
        return {self.INPUT_PROBE: OptionalType(LatencyProbeTensor())}

    def output_spec(self) -> RetargeterIOType:
        return {self.OUTPUT_RESPONSE: OptionalType(LatencyProbeTensor())}

    def _compute_fn(
        self, inputs: RetargeterIO, outputs: RetargeterIO, context: ComputeContext
    ) -> None:
        probe = inputs[self.INPUT_PROBE]
        out = outputs[self.OUTPUT_RESPONSE]
        if probe.is_none:
            out.set_none()
            return

        value = np.asarray(probe[PROBE_VALUE_INDEX], dtype=np.float32).copy()
        value[0] = -value[0]
        sequence = np.asarray(probe[PROBE_SEQUENCE_INDEX], dtype=np.uint32).copy()
        out[PROBE_VALUE_INDEX] = value
        out[PROBE_SEQUENCE_INDEX] = sequence


def _make_output_adapter() -> SchemaPushOutputAdapter:
    import isaacteleop.deviceio_trackers as deviceio_trackers

    def pack_sample(
        _endpoint: str, values: tuple[np.ndarray, ...]
    ) -> LatencyProbeResponse:
        value = float(values[PROBE_VALUE_INDEX][0])
        sequence = int(values[PROBE_SEQUENCE_INDEX][0])
        return LatencyProbeResponse(sequence=sequence, value=value)

    return SchemaPushOutputAdapter(
        deviceio_trackers.LatencyProbeResponsePushTracker(
            OUT_COLLECTION_ID, "latency_probe_response"
        ),
        LatencyProbeTensor(),
        pack_sample,
        endpoints=("device",),
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    CloudXRLauncher.add_launcher_arguments(parser)
    args = parser.parse_args()

    source = LatencyProbeSource("probe_source", collection_id=IN_COLLECTION_ID)
    invert = InvertFloat("invert")
    adapter = _make_output_adapter()
    sink = DeviceOutputSink("probe_sink", adapter)

    invert_graph = invert.connect({InvertFloat.INPUT_PROBE: source.output("probe")})
    sink_graph = sink.connect(
        {"device": invert_graph.output(InvertFloat.OUTPUT_RESPONSE)}
    )

    pipeline = OutputCombiner(
        {"response": invert_graph.output(InvertFloat.OUTPUT_RESPONSE)}
    )

    plugins = []
    if PLUGIN_ROOT_DIR.exists():
        plugins.append(
            PluginConfig(
                plugin_name="latency_probe",
                plugin_root_id="latency_probe",
                search_paths=[PLUGIN_ROOT_DIR],
                plugin_args=[IN_COLLECTION_ID, OUT_COLLECTION_ID],
            )
        )

    config = TeleopSessionConfig(
        app_name=APP_NAME,
        pipeline=pipeline,
        plugins=plugins,
        sinks=[sink_graph],
    )

    print(
        f"{APP_NAME}: waiting for plugin RTT stats on stderr/stdout "
        f"(collections in={IN_COLLECTION_ID}, out={OUT_COLLECTION_ID})"
    )

    try:
        with CloudXRLauncher.launch_context(args), TeleopSession(config) as session:
            frame_duration = 1.0 / FPS
            while True:
                session.step()
                time.sleep(frame_duration)
    except KeyboardInterrupt:
        print(f"\n{APP_NAME}: stopped")


if __name__ == "__main__":
    main()
