// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#pragma once

#include "oglo_config.hpp"

#include <chrono>
#include <cstddef>
#include <cstdint>
#include <functional>
#include <memory>
#include <string>

namespace plugins
{
namespace oglo_tactile
{

// OGLO BLE GATT identifiers (firmware OGLO-MT-RDR-02, all schema revisions).
namespace ble_uuids
{
constexpr const char* kService = "4652535f-424c-4500-0000-000000000001";
constexpr const char* kNotify = "4652535f-424c-4500-0001-000000000001"; // tactile + IMU stream
constexpr const char* kConfig = "4652535f-424c-4500-0002-000000000001"; // device manifest (JSON)
} // namespace ble_uuids

//! Advertised BLE name for a hand, e.g. "OGLO LEFT".
std::string advertised_name_for(Side side);

//! Abstract transport for one OGLO glove.
//!
//! The interface is deliberately backend-agnostic so the concrete BLE library
//! can be swapped without touching the parser/plugin (the upstream choice is a
//! licensing decision — see the plugin README). Notifications are delivered on
//! the backend's own thread; the @c NotifyCallback must therefore be
//! thread-safe and must not block.
class OgloBleClient
{
public:
    using NotifyCallback = std::function<void(const uint8_t* data, std::size_t len)>;
    using StateCallback = std::function<void(bool connected)>;

    virtual ~OgloBleClient() = default;

    //! Scan for the glove matching @p side (by advertised name, LE transport),
    //! connect, and read the Config characteristic.
    //! @return the Config JSON payload.
    //! @throws std::runtime_error on scan/connect/read failure or timeout.
    virtual std::string connect(Side side, std::chrono::milliseconds timeout) = 0;

    //! Subscribe to the notify characteristic. @p cb runs on the BLE thread.
    virtual void subscribe(NotifyCallback cb) = 0;

    //! Register an optional connection-state observer (connect / drop events).
    virtual void on_state_change(StateCallback cb) = 0;

    //! Disconnect and quiesce notifications: after this returns, the backend
    //! must not invoke the @c NotifyCallback again until the next subscribe().
    //! This lets the caller safely re-read geometry and re-subscribe on reconnect.
    virtual void disconnect() = 0;
};

//! Construct the BLE backend (BlueZ over libdbus).
//!
//! @param device_name_override If non-empty, scan for this exact advertised
//!        name instead of the side-derived default (useful when several gloves
//!        are nearby and need to be pinned by name).
std::unique_ptr<OgloBleClient> make_ble_client(std::string device_name_override = "");

} // namespace oglo_tactile
} // namespace plugins
