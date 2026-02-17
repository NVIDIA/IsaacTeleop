# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

# ==============================================================================
# McapFrame schema generation
# ==============================================================================
# mcap_frame.fbs includes oak.fbs from the core schema directory,
# so we pass both directories as -I paths to flatc.

set(MCAP_FBS_OUT ${CMAKE_CURRENT_BINARY_DIR}/generated)
set(CORE_FBS_DIR ${CMAKE_SOURCE_DIR}/src/core/schema/fbs)
set(CORE_FBS_GENERATED ${CMAKE_BINARY_DIR}/src/core/schema/fbs/generated/schema)

add_custom_command(
    OUTPUT
        ${MCAP_FBS_OUT}/mcap_frame_generated.h
        ${MCAP_FBS_OUT}/mcap_frame_bfbs_generated.h
    COMMAND ${CMAKE_COMMAND} -E make_directory ${MCAP_FBS_OUT}
    COMMAND $<TARGET_FILE:flatc>
            --cpp
            --cpp-ptr-type std::shared_ptr
            --gen-object-api
            --gen-mutable
            --schema
            --bfbs-gen-embed
            --reflect-names
            --reflect-types
            -I ${CMAKE_CURRENT_SOURCE_DIR}
            -I ${CORE_FBS_DIR}
            -o ${MCAP_FBS_OUT}
            ${CMAKE_CURRENT_SOURCE_DIR}/mcap_frame.fbs
    DEPENDS ${CMAKE_CURRENT_SOURCE_DIR}/mcap_frame.fbs flatc
    COMMENT "Generating FlatBuffers C++ for mcap_frame.fbs"
    VERBATIM
)

add_custom_target(mcap_frame_schema_generation
    DEPENDS
        ${MCAP_FBS_OUT}/mcap_frame_generated.h
        ${MCAP_FBS_OUT}/mcap_frame_bfbs_generated.h
)

# ==============================================================================
# MCAP Frame Sink library
# ==============================================================================

add_library(oak_mcap STATIC
    mcap_frame_sink.cpp
)

add_dependencies(oak_mcap mcap_frame_schema_generation)

target_include_directories(oak_mcap
    PUBLIC
        $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}>
        $<BUILD_INTERFACE:${OAK_CORE_INCLUDE_DIR}>
    PRIVATE
        ${MCAP_FBS_OUT}
        ${CORE_FBS_GENERATED}
)

target_link_libraries(oak_mcap
    PUBLIC
        isaacteleop_schema
        mcap::mcap
)
