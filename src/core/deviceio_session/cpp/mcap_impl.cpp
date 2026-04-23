// SPDX-FileCopyrightText: Copyright (c) 2025-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

// MCAP is header-only: exactly one TU in the library must define
// MCAP_IMPLEMENTATION and include every MCAP header whose symbols are needed.
// deviceio_session.cpp uses the writer; replay_session.cpp uses the reader.
#define MCAP_IMPLEMENTATION
#include <mcap/reader.hpp>
#include <mcap/writer.hpp>
