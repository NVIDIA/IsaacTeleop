// SPDX-FileCopyrightText: Copyright (c) 2026 j-mex. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#pragma once

#include <oxr_utils/oxr_session_handles.hpp>
#include <pusherio/schema_pusher.hpp>

#include <cstddef>
#include <string>

namespace plugins
{
namespace jmex
{

class ReceiverSession;

//! Publishes a MOXI channel's actuated joints as ``JointStateOutput`` on the generic joint-space
//! device path. Takes session handles rather than owning an ``OpenXRSession``, so publishers can
//! share one session.
class JointStatePublisher
{
public:
    /*!
     * @brief Upper bound on one serialized ``JointStateOutput``, in bytes.
     *
     * Must match the consumer's tracker. ``JointStateSource`` constructs its ``JointStateTracker``
     * with the default and offers no way to raise it, so this is a hard budget: publishing only the
     * actuated joints is what keeps a full humanoid inside it.
     */
    static constexpr size_t MAX_FLATBUFFER_SIZE = 4096;

    JointStatePublisher(const core::OpenXRSessionHandles& handles, const std::string& collection_id);

    //! Serialize the session's current joint values and push one sample. Call once per delivered
    //! frame -- see ReceiverSession::poll().
    void publish(const ReceiverSession& receiver);

private:
    std::string collection_id_;
    core::SchemaPusher pusher_;
};

} // namespace jmex
} // namespace plugins
