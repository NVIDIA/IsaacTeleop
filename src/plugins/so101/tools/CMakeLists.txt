# SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

# Standalone servo printer tool — no OpenXR dependency, only the Feetech driver.
add_executable(so101_printer
    so101_printer.cpp
    ${CMAKE_CURRENT_SOURCE_DIR}/../feetech_driver.cpp
)

target_include_directories(so101_printer PRIVATE
    ${CMAKE_CURRENT_SOURCE_DIR}/..
)

install(TARGETS so101_printer RUNTIME DESTINATION plugins/so101/tools)
