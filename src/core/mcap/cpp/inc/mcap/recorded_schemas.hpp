// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#pragma once

#include <mcap/reader.hpp>

#include <string>
#include <vector>

namespace core
{

/*!
 * @brief What a recording says it was written under: its Channel and Schema records.
 *
 * Replay opens one McapReader per tracker, so that crossing a chunk boundary in one cannot
 * disturb another's buffered message data, but what the file was written under belongs to
 * the file rather than to any one reader. Reading it once and handing the result to every
 * viewer is what keeps a recording with no summary section from being scanned end to end
 * once per tracker -- a full pass over the data section each time, on a path that runs
 * before the first frame.
 *
 * Self-contained once built: it copies the records out, so it outlives the reader it came
 * from.
 */
class RecordedSchemas
{
public:
    //! One channel the recording declares, with the schema it names.
    struct Channel
    {
        std::string topic;
        //! What the channel says its message bytes are. Only "flatbuffer" channels are read.
        std::string message_encoding;
        //! Null when the channel declares no schema at all.
        mcap::SchemaPtr schema;
    };

    /*!
     * @brief No recording at all.
     *
     * A session whose trackers are all push-fed names no file to replay. Declaring nothing is
     * the honest answer for one, and it is compatible with every reader by construction: a
     * schema that is not there cannot be one this build would misread. Distinct from a file
     * that was named and could not be read, which is an error and raises.
     */
    RecordedSchemas() = default;

    /*!
     * @brief Read every Channel and Schema record `reader`'s file declares.
     *
     * The summary section normally names them. A writer killed before it could flush one
     * leaves them in the data section, and a summary that names channels but does not repeat
     * their schemas is the same gap from the other side; both take the same scan.
     *
     * @throws std::runtime_error when neither route yields them, which is a recording too
     *         damaged to say what it was written under.
     */
    explicit RecordedSchemas(mcap::McapReader& reader);

    const std::vector<Channel>& channels() const
    {
        return channels_;
    }

private:
    std::vector<Channel> channels_;
};

} // namespace core
