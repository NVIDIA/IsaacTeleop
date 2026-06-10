# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

add_executable(so101_leader_plugin
    main.cpp
    so101_leader_plugin.cpp
)

target_link_libraries(so101_leader_plugin PRIVATE
    pusherio::pusherio
    oxr::oxr_core
    isaacteleop_schema
)

install(TARGETS so101_leader_plugin RUNTIME DESTINATION plugins/so101_leader)
install(FILES plugin.yaml README.md DESTINATION plugins/so101_leader)
