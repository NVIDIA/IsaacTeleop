# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
#
# Helper script invoked from add_custom_command to convert a SPIR-V
# binary into a C header containing an inline constexpr byte array.
# Driven by command-line variables: SPV_PATH, HEADER_PATH, VAR_NAME.
#
# Output (HEADER_PATH) looks like:
#   #pragma once
#   #include <cstddef>
#   #include <cstdint>
#   namespace viz::shaders {
#   inline constexpr alignas(uint32_t) unsigned char kVarName[] = {
#       0x03, 0x02, 0x23, 0x07, ...
#   };
#   inline constexpr size_t kVarNameSize = sizeof(kVarName);
#   } // namespace viz::shaders

if(NOT DEFINED SPV_PATH OR NOT DEFINED HEADER_PATH OR NOT DEFINED VAR_NAME)
    message(FATAL_ERROR "compile_shader.cmake requires SPV_PATH, HEADER_PATH, VAR_NAME")
endif()

file(READ "${SPV_PATH}" SPV_CONTENT HEX)
string(LENGTH "${SPV_CONTENT}" SPV_HEX_LEN)
math(EXPR SPV_BYTE_LEN "${SPV_HEX_LEN} / 2")
if(SPV_BYTE_LEN EQUAL 0)
    message(FATAL_ERROR "compile_shader.cmake: ${SPV_PATH} is empty")
endif()

# Format every two hex chars as 0xab,. Single long line — SPIR-V binaries
# are small (~KB) and compilers handle long initializer lines fine.
string(REGEX REPLACE "([0-9a-f][0-9a-f])" "0x\\1, " SPV_BYTES "${SPV_CONTENT}")

set(HEADER_CONTENT
"// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0
//
// AUTO-GENERATED FROM ${SPV_PATH} BY compile_shader.cmake. DO NOT EDIT.

#pragma once

#include <cstddef>
#include <cstdint>

namespace viz::shaders
{

alignas(uint32_t) inline constexpr unsigned char ${VAR_NAME}[] = {
    ${SPV_BYTES}
};
inline constexpr size_t ${VAR_NAME}Size = sizeof(${VAR_NAME});

} // namespace viz::shaders
")

file(WRITE "${HEADER_PATH}" "${HEADER_CONTENT}")
