# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

add_executable(rebot_devarm_leader_plugin
    main.cpp
    rebot_devarm_leader_plugin.cpp
    damiao_bus.cpp
    robstride_bus.cpp
)

target_link_libraries(rebot_devarm_leader_plugin PRIVATE
    pusherio::pusherio
    oxr::oxr_core
    isaacteleop_schema
)

# The CAN bus implementations are SocketCAN, so their bodies live behind
# #ifdef __linux__ and compile to throwing stubs elsewhere. Clang then correctly
# reports the (still-declared) private members as unused. The warning is real but
# unactionable off Linux, so suppress it only there and only for this target;
# on Linux the fields are used and the warning stays live. GCC has no such warning.
if(NOT CMAKE_SYSTEM_NAME STREQUAL "Linux")
    target_compile_options(rebot_devarm_leader_plugin PRIVATE
        $<$<CXX_COMPILER_ID:Clang,AppleClang>:-Wno-unused-private-field>
    )
endif()

install(TARGETS rebot_devarm_leader_plugin RUNTIME DESTINATION plugins/rebot_devarm_leader)
install(FILES plugin.yaml README.md DESTINATION plugins/rebot_devarm_leader)
