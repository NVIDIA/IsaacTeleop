// SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

/*!
 * @brief Demo application that pushes serialized FlatBuffer Generic3AxisPedalOutput data into the OpenXR runtime.
 *
 * This application demonstrates using the SchemaPusherBase class to push Generic3AxisPedalOutput FlatBuffer
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
 */
class Generic3AxisPedalPusher : public core::SchemaPusherBase
{
public:
    Generic3AxisPedalPusher(const core::OpenXRSessionHandles& handles, const std::string& collection_id)
        : SchemaPusherBase(handles,
                           core::SchemaPusherConfig{ .collection_id = collection_id,
                                                     .max_flatbuffer_size = MAX_FLATBUFFER_SIZE,
                                                     .tensor_identifier = "generic_3axis_pedal",
                                                     .localized_name = "Generic 3-Axis Pedal Pusher Demo",
                                                     .app_name = "Generic3AxisPedalPusher" })
    {
    }

    /*!
     * @brief Push a Generic3AxisPedalOutput message.
     * @param data The Generic3AxisPedalOutputT native object to serialize and push.
     * @return true on success, false on failure.
     */
    bool push(const core::Generic3AxisPedalOutputT& data)
    {
        flatbuffers::FlatBufferBuilder builder(config().max_flatbuffer_size);
        auto offset = core::Generic3AxisPedalOutput::Pack(builder, &data);
        builder.Finish(offset);
        return push_buffer(builder.GetBufferPointer(), builder.GetSize());
    }
};

int main()
{
    std::cout << "Schema Pusher (collection: " << COLLECTION_ID << ")" << std::endl;

    // Step 1: Create OpenXR session with required extensions for pushing tensor data
    std::cout << "[Step 1] Creating OpenXR session with tensor push extensions..." << std::endl;

    std::vector<std::string> required_extensions = { "XR_NVX1_push_tensor", "XR_NVX1_tensor_data" };

    auto oxr_session = core::OpenXRSession::Create("SchemaPusher", required_extensions);
    if (!oxr_session)
    {
        std::cerr << "Failed to create OpenXR session" << std::endl;
        return 1;
    }

    std::cout << "  OpenXR session created" << std::endl;

    // Step 2: Create the pusher with the session handles
    std::cout << "[Step 2] Creating Generic3AxisPedalPusher..." << std::endl;

    std::unique_ptr<Generic3AxisPedalPusher> pusher;
    try
    {
        auto handles = oxr_session->get_handles();
        pusher = std::make_unique<Generic3AxisPedalPusher>(handles, COLLECTION_ID);
    }
    catch (const std::exception& e)
    {
        std::cerr << "Failed to create pusher: " << e.what() << std::endl;
        return 1;
    }

    // Step 3: Push samples
    std::cout << "[Step 3] Pushing samples..." << std::endl;

    for (int i = 0; i < MAX_SAMPLES; ++i)
    {
        // Generate varying pedal values (sinusoidal)
        float t = static_cast<float>(i) * 0.1f;
        float left_pedal = (std::sin(t) + 1.0f) * 0.5f; // 0.0 to 1.0
        float right_pedal = (std::cos(t) + 1.0f) * 0.5f; // 0.0 to 1.0
        float rudder = std::sin(t * 0.5f); // -1.0 to 1.0

        // Create and populate Generic3AxisPedalOutputT
        core::Generic3AxisPedalOutputT pedal_output;
        pedal_output.left_pedal = left_pedal;
        pedal_output.right_pedal = right_pedal;
        pedal_output.rudder = rudder;

        auto now = std::chrono::steady_clock::now();
        auto ns = std::chrono::duration_cast<std::chrono::nanoseconds>(now.time_since_epoch()).count();
        pedal_output.timestamp = std::make_shared<core::Timestamp>(ns, ns);

        if (pusher->push(pedal_output))
        {
            std::cout << "Pushed sample " << i << std::fixed << std::setprecision(3) << " [left=" << left_pedal
                      << ", right=" << right_pedal << ", rudder=" << rudder << "]" << std::endl;
        }

        std::this_thread::sleep_for(std::chrono::milliseconds(50));
    }

    std::cout << "\nTotal samples pushed: " << pusher->get_push_count() << std::endl;
    return 0;
}
