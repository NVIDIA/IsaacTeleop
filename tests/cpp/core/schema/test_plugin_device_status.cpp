// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#include <catch2/catch_test_macros.hpp>
#include <flatbuffers/flatbuffers.h>
#include <schema/plugin_device_status_generated.h>

#include <memory>

#define VT(field) (field + 2) * 2

static_assert(core::PluginDeviceStatus::VT_PATH == VT(0));
static_assert(core::PluginDeviceStatus::VT_STATE == VT(1));
static_assert(core::PluginDeviceStatus::VT_REASON == VT(2));
static_assert(core::PluginDeviceStatus::VT_ERROR == VT(3));
static_assert(core::PluginDeviceStatusSnapshot::VT_SCHEMA_VERSION == VT(0));
static_assert(core::PluginDeviceStatusSnapshot::VT_REPORT_TIME_NS == VT(1));
static_assert(core::PluginDeviceStatusSnapshot::VT_DEVICES == VT(2));
static_assert(core::PluginDeviceStatusSnapshotRecord::VT_DATA == VT(0));
static_assert(core::PluginDeviceStatusSnapshotRecord::VT_TIMESTAMP == VT(1));

static_assert(core::PluginDeviceState_UNKNOWN == 0);
static_assert(core::PluginDeviceState_CONNECTED == 1);
static_assert(core::PluginDeviceState_DISCONNECTED == 2);
static_assert(core::PluginDeviceState_DEGRADED == 3);
static_assert(core::PluginDeviceState_FAILED == 4);
static_assert(core::PluginDeviceState_DISABLED == 5);

static_assert(core::PluginDeviceReason_NONE == 0);
static_assert(core::PluginDeviceReason_NO_HARDWARE_SIGNAL == 1);
static_assert(core::PluginDeviceReason_HARDWARE_CONNECTED == 2);
static_assert(core::PluginDeviceReason_HARDWARE_DISCONNECTED == 3);
static_assert(core::PluginDeviceReason_RECOVERING == 4);
static_assert(core::PluginDeviceReason_PARTIAL_FUNCTIONALITY == 5);
static_assert(core::PluginDeviceReason_DEVICE_ERROR == 6);
static_assert(core::PluginDeviceReason_DISABLED_BY_CONFIGURATION == 7);

TEST_CASE("Plugin device status fields are optional", "[schema][plugin_device_status]")
{
    flatbuffers::FlatBufferBuilder builder;
    builder.Finish(core::CreatePluginDeviceStatusSnapshotRecord(builder));

    const auto* record = flatbuffers::GetRoot<core::PluginDeviceStatusSnapshotRecord>(builder.GetBufferPointer());
    REQUIRE(record != nullptr);
    CHECK(record->data() == nullptr);
    CHECK(record->timestamp() == nullptr);
}

TEST_CASE("Plugin device status snapshot round-trips", "[schema][plugin_device_status]")
{
    core::PluginDeviceStatusSnapshotT native;
    native.schema_version = 1;
    native.report_time_ns = 42;

    auto device = std::make_shared<core::PluginDeviceStatusT>();
    device->path = "/input/left_hand";
    device->state = core::PluginDeviceState_DEGRADED;
    device->reason = core::PluginDeviceReason_PARTIAL_FUNCTIONALITY;
    device->error = "finger sensor unavailable";
    native.devices.push_back(std::move(device));

    flatbuffers::FlatBufferBuilder builder;
    builder.Finish(core::PluginDeviceStatusSnapshot::Pack(builder, &native));

    const auto* snapshot = flatbuffers::GetRoot<core::PluginDeviceStatusSnapshot>(builder.GetBufferPointer());
    REQUIRE(snapshot != nullptr);
    CHECK(snapshot->schema_version() == 1);
    CHECK(snapshot->report_time_ns() == 42);
    REQUIRE(snapshot->devices() != nullptr);
    REQUIRE(snapshot->devices()->size() == 1);
    CHECK(snapshot->devices()->Get(0)->path()->str() == "/input/left_hand");
    CHECK(snapshot->devices()->Get(0)->state() == core::PluginDeviceState_DEGRADED);
    CHECK(snapshot->devices()->Get(0)->reason() == core::PluginDeviceReason_PARTIAL_FUNCTIONALITY);
    CHECK(snapshot->devices()->Get(0)->error()->str() == "finger sensor unavailable");
}

#undef VT
