<!--
SPDX-FileCopyrightText: Copyright (c) 2025-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
SPDX-License-Identifier: Apache-2.0
-->

# Latency probe plugin

Teaching plugin for the **generic vendor I/O path**: synthetic float samples flow
plugin → Teleop (``LatencyProbeRequest``), through a retargeter that inverts the
value, then Teleop → plugin (``LatencyProbeResponse``). The plugin prints RTT
**avg / min / max** every five seconds.

## Collections

| Direction | Collection ID | Schema | Tensor identifier |
| --- | --- | --- | --- |
| Plugin → Teleop | ``latency_probe_in`` | ``LatencyProbeRequest`` | ``latency_probe_request`` |
| Teleop → plugin | ``latency_probe_out`` | ``LatencyProbeResponse`` | ``latency_probe_response`` |

Run the host example in ``examples/latency_probe/python/latency_probe_example.py``
with this plugin started via ``PluginManager`` (or run the binary manually with the
same collection IDs). ``PluginManager`` appends ``--plugin-root-id=...``; ``main``
skips that flag and only treats other positionals as collection overrides.

## Build

Built when ``BUILD_PLUGINS=ON``. Installed to ``plugins/latency_probe/``.
