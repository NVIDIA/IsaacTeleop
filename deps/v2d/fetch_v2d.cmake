# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

foreach(_required GIT_EXECUTABLE V2D_REPOSITORY V2D_COMMIT V2D_SOURCE_DIR)
    if(NOT DEFINED ${_required})
        message(FATAL_ERROR "${_required} is required")
    endif()
endforeach()

if(EXISTS "${V2D_SOURCE_DIR}/.git")
    execute_process(
        COMMAND "${GIT_EXECUTABLE}" rev-parse HEAD
        WORKING_DIRECTORY "${V2D_SOURCE_DIR}"
        OUTPUT_VARIABLE _current_commit
        OUTPUT_STRIP_TRAILING_WHITESPACE
        RESULT_VARIABLE _rev_parse_result
    )
    if(_rev_parse_result EQUAL 0 AND _current_commit STREQUAL V2D_COMMIT)
        return()
    endif()
endif()

file(REMOVE_RECURSE "${V2D_SOURCE_DIR}")
execute_process(
    COMMAND "${CMAKE_COMMAND}" -E env GIT_LFS_SKIP_SMUDGE=1
        "${GIT_EXECUTABLE}" clone --filter=blob:none --no-checkout
        "${V2D_REPOSITORY}" "${V2D_SOURCE_DIR}"
    COMMAND_ERROR_IS_FATAL ANY
)
execute_process(
    COMMAND "${GIT_EXECUTABLE}" sparse-checkout set
        "LICENSE"
        "robotic_grounding/source/robotic_grounding/robotic_grounding/__init__.py"
        "robotic_grounding/source/robotic_grounding/robotic_grounding/retarget"
        "robotic_grounding/source/robotic_grounding/robotic_grounding/assets/xmls/sharpawave"
    WORKING_DIRECTORY "${V2D_SOURCE_DIR}"
    COMMAND_ERROR_IS_FATAL ANY
)
execute_process(
    COMMAND "${CMAKE_COMMAND}" -E env GIT_LFS_SKIP_SMUDGE=1
        "${GIT_EXECUTABLE}" checkout --detach "${V2D_COMMIT}"
    WORKING_DIRECTORY "${V2D_SOURCE_DIR}"
    COMMAND_ERROR_IS_FATAL ANY
)
