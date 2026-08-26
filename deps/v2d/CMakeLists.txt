# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

include(FetchContent)
find_package(Git REQUIRED)

set(VIDEO_TO_DATA_REPOSITORY "https://github.com/nvidia-isaac/video_to_data.git")
set(VIDEO_TO_DATA_COMMIT "751b74453d488139f754dae488e6ffb19791d927")
set(VIDEO_TO_DATA_SOURCE_DIR "${FETCHCONTENT_BASE_DIR}/video_to_data-src")

# FetchContent owns the checkout, while the custom download command keeps it to
# the five retargeting modules and Sharpa assets Teleop actually packages.
FetchContent_Declare(
    video_to_data
    SOURCE_DIR "${VIDEO_TO_DATA_SOURCE_DIR}"
    DOWNLOAD_COMMAND
        "${CMAKE_COMMAND}"
        "-DGIT_EXECUTABLE=${GIT_EXECUTABLE}"
        "-DV2D_REPOSITORY=${VIDEO_TO_DATA_REPOSITORY}"
        "-DV2D_COMMIT=${VIDEO_TO_DATA_COMMIT}"
        "-DV2D_SOURCE_DIR=${VIDEO_TO_DATA_SOURCE_DIR}"
        -P "${CMAKE_CURRENT_SOURCE_DIR}/fetch_v2d.cmake"
    UPDATE_COMMAND ""
    PATCH_COMMAND ""
    CONFIGURE_COMMAND ""
    BUILD_COMMAND ""
    INSTALL_COMMAND ""
)
FetchContent_MakeAvailable(video_to_data)

set(_robotic_grounding_source
    "${VIDEO_TO_DATA_SOURCE_DIR}/robotic_grounding/source/robotic_grounding/robotic_grounding")
if(NOT EXISTS "${_robotic_grounding_source}/retarget/hand_kinematics.py")
    message(FATAL_ERROR "Public V2D checkout is missing robotic_grounding retargeting sources")
endif()

set(ROBOTIC_GROUNDING_STAGED_DIR
    "${CMAKE_BINARY_DIR}/_deps/robotic_grounding"
    CACHE INTERNAL "Curated public V2D robotic_grounding package")
execute_process(
    COMMAND "${Python3_EXECUTABLE}" "${CMAKE_CURRENT_SOURCE_DIR}/stage_robotic_grounding.py"
        --source-root "${VIDEO_TO_DATA_SOURCE_DIR}"
        --output-root "${ROBOTIC_GROUNDING_STAGED_DIR}"
    RESULT_VARIABLE _stage_result
    ERROR_VARIABLE _stage_error
)
if(NOT _stage_result EQUAL 0)
    message(FATAL_ERROR "Failed to stage robotic_grounding: ${_stage_error}")
endif()
message(STATUS "Staged public V2D robotic_grounding at ${ROBOTIC_GROUNDING_STAGED_DIR}")
