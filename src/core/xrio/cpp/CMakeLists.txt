cmake_minimum_required(VERSION 3.20)

# If this is being built standalone, declare a project
if(CMAKE_SOURCE_DIR STREQUAL CMAKE_CURRENT_SOURCE_DIR)
    project(xrio_core VERSION 1.0.0 LANGUAGES CXX)
    set(CMAKE_CXX_STANDARD 17)
    set(CMAKE_CXX_STANDARD_REQUIRED ON)
endif()

# Ensure OpenXR target is available (built from submodule by parent)
if(NOT TARGET OpenXR::OpenXR)
    if(TARGET openxr_loader)
        add_library(OpenXR::OpenXR ALIAS openxr_loader)
    else()
        message(FATAL_ERROR "OpenXR target not found. Make sure OpenXR SDK submodule is built first.")
    endif()
endif()

# Find OXR library
if(NOT TARGET oxr::oxr_core)
    find_library(OXR_LIBRARY
        NAMES oxr_core liboxr_core
        PATHS ${CMAKE_BINARY_DIR}/../oxr/cpp ${CMAKE_BINARY_DIR}/../../oxr/cpp /usr/lib /usr/local/lib
        PATH_SUFFIXES lib lib64
    )
    
    find_path(OXR_INCLUDE_DIR
        NAMES oxr/oxr_session.hpp
        PATHS ${CMAKE_SOURCE_DIR}/../../oxr/cpp/inc ${CMAKE_SOURCE_DIR}/../oxr/cpp/inc /usr/include /usr/local/include
        PATH_SUFFIXES include
    )
    
    if(OXR_LIBRARY AND OXR_INCLUDE_DIR)
        add_library(oxr::oxr_core UNKNOWN IMPORTED)
        set_target_properties(oxr::oxr_core PROPERTIES
            IMPORTED_LOCATION "${OXR_LIBRARY}"
            INTERFACE_INCLUDE_DIRECTORIES "${OXR_INCLUDE_DIR}"
        )
        message(STATUS "Found OXR: ${OXR_LIBRARY}")
        message(STATUS "  Include: ${OXR_INCLUDE_DIR}")
    else()
        message(STATUS "OXR library not found, will build from source")
    endif()
endif()

# Core XRIO tracking library (static for distribution)
add_library(xrio_core STATIC
    handtracker.cpp
    headtracker.cpp
    teleop_session.cpp
    inc/xrio/tracker.hpp
    inc/xrio/handtracker.hpp
    inc/xrio/headtracker.hpp
    inc/xrio/teleop_session.hpp
)

target_include_directories(xrio_core
    INTERFACE
        $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}/inc>
        $<INSTALL_INTERFACE:include>
)

target_link_libraries(xrio_core
    PUBLIC
        OpenXR::OpenXR
        oxr::oxr_core
)

# Create alias for consistent naming
add_library(xrio::xrio_core ALIAS xrio_core)

# Optional: Install for distribution
install(TARGETS xrio_core
    ARCHIVE DESTINATION lib
    INCLUDES DESTINATION include
)

install(DIRECTORY inc/xrio
    DESTINATION include
)

