# SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

add_executable(haply_hand_tracker_printer
  haply_hand_tracker_printer.cpp
)

target_include_directories(haply_hand_tracker_printer
  PRIVATE
    ${CMAKE_CURRENT_SOURCE_DIR}/../third_party
)

target_link_libraries(haply_hand_tracker_printer
  PRIVATE
    Threads::Threads
)

set_target_properties(haply_hand_tracker_printer PROPERTIES
  CXX_VISIBILITY_PRESET hidden
  VISIBILITY_INLINES_HIDDEN YES
  RUNTIME_OUTPUT_DIRECTORY "${CMAKE_BINARY_DIR}/bin"
)
