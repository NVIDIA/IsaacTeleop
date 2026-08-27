// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#pragma once

#include <cstdint>
#include <span>
#include <string>
#include <string_view>

namespace core
{

//! How a recording's embedded binary schema relates to the one the reader was built from.
enum class SchemaCompat
{
    //! Byte-identical bfbs.
    Identical,
    //! Differs, but every field the generated accessors read keeps its id, type and offset.
    Compatible,
    //! Decoding with the compiled-in accessors would misread the recorded bytes.
    Incompatible,
};

struct SchemaCompatResult
{
    SchemaCompat status = SchemaCompat::Identical;
    //! Empty when Identical; otherwise what differs, phrased for a log line.
    std::string detail;
};

/*!
 * @brief Compare a recording's embedded bfbs against the compiled-in one.
 *
 * `recorded` is file data and is verified as a binary schema before anything walks it.
 * A struct that gained a field, a reused field id, and a widened scalar all land in
 * Incompatible; a table that only gained fields at the end lands in Compatible.
 *
 * The root type the reader expects is read out of `compiled` rather than passed in, so a
 * caller cannot name one schema and hand over another.
 *
 * @param recorded bfbs bytes read from the MCAP Schema record.
 * @param compiled bfbs bytes from the generated `RecordT::BinarySchema`.
 * @throws std::logic_error if `compiled` is not a deserializable binary schema.
 */
SchemaCompatResult check_schema_compat(std::span<const uint8_t> recorded, std::span<const uint8_t> compiled);

/*!
 * @brief Act on a comparison result: reject what cannot be read, report what merely differs.
 *
 * A grade describes the recording, not any one message, so callers settle it once per schema
 * when the file is opened.
 *
 * @param result  Grade for a schema the recording carries.
 * @param context Channel topic, used to locate the mismatch in the message.
 * @throws std::runtime_error when `result` is Incompatible.
 */
void enforce_schema_compat(const SchemaCompatResult& result, std::string_view context);

} // namespace core
