# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

add_executable(orbbec_camera_tests
    test_orbbec_camera.cpp
)

target_link_libraries(orbbec_camera_tests
    PRIVATE
        orbbec::camera_core
        Catch2::Catch2WithMain
)

catch_discover_tests(orbbec_camera_tests)
