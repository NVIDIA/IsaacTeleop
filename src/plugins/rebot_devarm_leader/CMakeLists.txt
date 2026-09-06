# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

add_executable(rebot_devarm_leader_plugin
    main.cpp
    rebot_devarm_leader_plugin.cpp
    damiao_bus.cpp
    robstride_bus.cpp
)

target_link_libraries(rebot_devarm_leader_plugin PRIVATE
    Teleop::plugin_utils
    pusherio::pusherio
    isaacteleop_schema
)

install(TARGETS rebot_devarm_leader_plugin RUNTIME DESTINATION plugins/rebot_devarm_leader)
install(FILES plugin.yaml README.md DESTINATION plugins/rebot_devarm_leader)
