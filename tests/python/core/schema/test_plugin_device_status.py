# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

from isaacteleop.schema import (
    DeviceDataTimestamp,
    PluginDeviceReason,
    PluginDeviceState,
    PluginDeviceStatus,
    PluginDeviceStatusSnapshot,
    PluginDeviceStatusSnapshotRecord,
)


def test_plugin_device_status_snapshot_is_an_encoded_read_only_view():
    device = PluginDeviceStatus(
        "/input/left",
        PluginDeviceState.DEGRADED,
        PluginDeviceReason.PARTIAL_FUNCTIONALITY,
        "finger sensor unavailable",
    )
    snapshot = PluginDeviceStatusSnapshot(1, 42, [device])

    assert snapshot.schema_version == 1
    assert snapshot.report_time_ns == 42
    assert len(snapshot.devices) == 1
    assert snapshot.devices[0].path == "/input/left"
    assert snapshot.devices[0].state == PluginDeviceState.DEGRADED
    assert snapshot.devices[0].reason == PluginDeviceReason.PARTIAL_FUNCTIONALITY
    assert snapshot.devices[0].error == "finger sensor unavailable"


def test_plugin_device_status_record_round_trips():
    snapshot = PluginDeviceStatusSnapshot()
    record = PluginDeviceStatusSnapshotRecord(snapshot, DeviceDataTimestamp(1, 2, 3))

    assert record.data.schema_version == 0
    assert record.data.devices == []
    assert record.timestamp.sample_time_local_common_clock == 2
