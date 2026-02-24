// SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

/*!
 * @brief Demo application that pushes serialized FlatBuffer Generic3AxisPedalOutput data into the OpenXR runtime.
 *
 * This application demonstrates using the SchemaPusher class to push Generic3AxisPedalOutput FlatBuffer
 * messages. The application creates the OpenXR session with required extensions and passes
 * the handles to the pusherio library.
 *
 * Note: Both pusher and reader agree on the schema (Generic3AxisPedalOutput from pedals.fbs), so the schema
 * does not need to be sent over the wire.
 */

#include "common_utils.hpp"

#include <flatbuffers/flatbuffers.h>
#include <oxr/oxr_session.hpp>
#include <pusherio/schema_pusher.hpp>
#include <schema/pedals_generated.h>

#include <chrono>
#include <cmath>
#include <iomanip>
#include <iostream>
#include <memory>
#include <thread>

using namespace schemaio_example;

/*!
 * @brief Generic3AxisPedalOutput-specific pusher that serializes and pushes foot pedal messages.
 *
 * Uses composition with SchemaPusher to handle the OpenXR tensor pushing.
 */
class Generic3AxisPedalPusher
{
public:
    Generic3AxisPedalPusher(const core::OpenXRSessionHandles& handles, const std::string& collection_id)
        : m_pusher(handles,
                   core::SchemaPusherConfig{ .collection_id = collection_id,
                                             .max_flatbuffer_size = MAX_FLATBUFFER_SIZE,
                                             .tensor_identifier = "generic_3axis_pedal",
                                             .localized_name = "Generic 3-Axis Pedal Pusher Demo",
                                             .app_name = "Generic3AxisPedalPusher" })
    {
    }

    /*!
     * @brief Push a Generic3AxisPedalOutput message.
     * @param data The Generic3AxisPedalOutput struct to serialize and push.
     * @throws std::runtime_error if the push fails.
     */
    void push(const core::Generic3AxisPedalOutput& data)
    {
        flatbuffers::FlatBufferBuilder builder(m_pusher.config().max_flatbuffer_size);
        core::Generic3AxisPedalOutputRecordBuilder record_builder(builder);
        record_builder.add_data(&data);
        builder.Finish(record_builder.Finish());

        m_pusher.push_buffer(builder.GetBufferPointer(), builder.GetSize());
    }

private:
    core::SchemaPusher m_pusher;
};

int main(int argc, char** argv)
try
{
    std::cout << "Schema Pusher (collection: " << COLLECTION_ID << ")" << std::endl;

    // Step 1: Create OpenXR session with required extensions for pushing tensor data
    std::cout << "[Step 1] Creating OpenXR session with tensor push extensions..." << std::endl;

    auto required_extensions = core::SchemaPusher::get_required_extensions();

    auto oxr_session = std::make_shared<core::OpenXRSession>("SchemaPusher", required_extensions);

    std::cout << "  OpenXR session created" << std::endl;

    // Step 2: Create the pusher with the session handles
    std::cout << "[Step 2] Creating Generic3AxisPedalPusher..." << std::endl;

    std::unique_ptr<Generic3AxisPedalPusher> pusher;
    auto handles = oxr_session->get_handles();
    pusher = std::make_unique<Generic3AxisPedalPusher>(handles, COLLECTION_ID);

    // Step 3: Push samples
    std::cout << "[Step 3] Pushing samples..." << std::endl;

    for (int i = 0; i < MAX_SAMPLES; ++i)
    {
        // Generate varying pedal values (sinusoidal)
        float t = static_cast<float>(i) * 0.1f;
        float left_pedal = (std::sin(t) + 1.0f) * 0.5f; // 0.0 to 1.0
        float right_pedal = (std::cos(t) + 1.0f) * 0.5f; // 0.0 to 1.0
        float rudder = std::sin(t * 0.5f); // -1.0 to 1.0

        core::Generic3AxisPedalOutput pedal_output{};
        pedal_output.mutate_is_active(true);
        pedal_output.mutate_left_pedal(left_pedal);
        pedal_output.mutate_right_pedal(right_pedal);
        pedal_output.mutate_rudder(rudder);

        auto now = std::chrono::steady_clock::now();
        auto ns = std::chrono::duration_cast<std::chrono::nanoseconds>(now.time_since_epoch()).count();
        pedal_output.mutable_timestamp() = core::Timestamp(ns, ns);

        pusher->push(pedal_output);
        std::cout << "Pushed sample " << i << std::fixed << std::setprecision(3) << " [left=" << left_pedal
                  << ", right=" << right_pedal << ", rudder=" << rudder << "]" << std::endl;

        std::this_thread::sleep_for(std::chrono::milliseconds(50));
    }

    return 0;
}
catch (const std::exception& e)
{
    std::cerr << argv[0] << ": " << e.what() << std::endl;
    return 1;
}
catch (...)
{
    std::cerr << argv[0] << ": Unknown error occurred" << std::endl;
    return 1;
}
