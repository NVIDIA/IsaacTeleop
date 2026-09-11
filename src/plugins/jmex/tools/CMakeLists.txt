# SPDX-FileCopyrightText: Copyright (c) 2026 j-mex. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

add_executable(jmex_joint_state_printer
    jmex_joint_state_printer.cpp
)

target_link_libraries(jmex_joint_state_printer
    PRIVATE
        isaac::jmex_plugin_core
        deviceio::deviceio_session
        deviceio::deviceio_trackers
        oxr::oxr_core
)

install(TARGETS jmex_joint_state_printer RUNTIME DESTINATION plugins/jmex)
