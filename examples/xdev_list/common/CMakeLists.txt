# SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

# Common library sources (minimal set for xdev_list headless app)
set(COMMON_SOURCES
    main_helpers.cpp
    main_helpers.hpp
    oxr_bundle.hpp
    oxr_creator.cpp
    oxr_creator.hpp
    )

# Create common library
add_library(examples_common STATIC ${COMMON_SOURCES})

target_include_directories(
	examples_common PUBLIC ${CMAKE_CURRENT_SOURCE_DIR}/.. ${CMAKE_CURRENT_SOURCE_DIR}
			       ${OpenXR_INCLUDE_DIRS}
	)

target_link_libraries(
	examples_common PUBLIC OpenXR::openxr_loader
	)

# Compiler warnings
target_compile_options(
	examples_common
	PRIVATE
		$<$<CXX_COMPILER_ID:GNU,Clang,AppleClang>:-Wall
		-Wextra
		-Wpedantic
		-Wno-missing-field-initializers>
		$<$<CXX_COMPILER_ID:MSVC>:/W4>
	)
