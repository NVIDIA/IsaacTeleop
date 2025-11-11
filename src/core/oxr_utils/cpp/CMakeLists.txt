cmake_minimum_required(VERSION 3.20)

# If this is being built standalone, declare a project
if(CMAKE_SOURCE_DIR STREQUAL CMAKE_CURRENT_SOURCE_DIR)
    project(oxr_utils VERSION 1.0.0 LANGUAGES CXX)
    set(CMAKE_CXX_STANDARD 17)
    set(CMAKE_CXX_STANDARD_REQUIRED ON)
endif()

# Ensure OpenXR headers target is available
if(NOT TARGET OpenXR::headers)
    message(FATAL_ERROR "OpenXR::headers target not found. Make sure OpenXR SDK is configured first.")
endif()

# OXR Utils - Header-only utility library for OpenXR types
# This library provides common OpenXR type definitions without linking to OpenXR loader
add_library(oxr_utils INTERFACE)

target_include_directories(oxr_utils
    INTERFACE
        $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}/inc>
        $<INSTALL_INTERFACE:include>
)

# Link with OpenXR::headers to get OpenXR header files (no loader linking)
target_link_libraries(oxr_utils
    INTERFACE
        OpenXR::headers
)

# Create alias for consistent naming
add_library(oxr::oxr_utils ALIAS oxr_utils)

# Optional: Install for distribution
install(TARGETS oxr_utils
    EXPORT oxr_utils-targets
    INCLUDES DESTINATION include
)

install(DIRECTORY inc/oxr_utils
    DESTINATION include
)

install(EXPORT oxr_utils-targets
    FILE oxr_utils-targets.cmake
    NAMESPACE oxr::
    DESTINATION lib/cmake/oxr_utils
)

