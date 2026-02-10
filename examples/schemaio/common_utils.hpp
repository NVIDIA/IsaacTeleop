// SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#pragma once

#include <cstddef>

namespace schemaio_example
{

//! Maximum size for serialized Generic3AxisPedalOutput FlatBuffer.
static constexpr size_t MAX_FLATBUFFER_SIZE = 256;

//! Maximum total samples to push/receive before exiting.
static constexpr int MAX_SAMPLES = 1000;

//! Collection ID shared between pusher and reader.
static constexpr const char* COLLECTION_ID = "generic_3axis_pedal";

} // namespace schemaio_example
