# SPDX-FileCopyrightText: Copyright (c) 2026 j-mex. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

add_library(jmex_plugin_core STATIC
    receiver_session.cpp
    joint_state_publisher.cpp
    inc/jmex/receiver_session.hpp
    inc/jmex/joint_state_publisher.hpp
)

target_include_directories(jmex_plugin_core
    INTERFACE
        $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}/inc>
)

# Public headers include schema_pusher.hpp and oxr_session_handles.hpp, so both targets propagate.
# The vendor SDK does not: no public header names it, and this library is the only caller -- what
# the plugin needs from it (the dialect, the version string) is behind jmex/receiver_session.hpp.
target_link_libraries(jmex_plugin_core
    PUBLIC
        pusherio::pusherio
        oxr::oxr_utils
    PRIVATE
        Moxi::Receiver
        isaacteleop_schema
)

set_target_properties(jmex_plugin_core PROPERTIES
    POSITION_INDEPENDENT_CODE ON
    CXX_VISIBILITY_PRESET hidden
    VISIBILITY_INLINES_HIDDEN YES
)

add_library(isaac::jmex_plugin_core ALIAS jmex_plugin_core)
