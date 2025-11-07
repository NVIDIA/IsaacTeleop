cmake_minimum_required(VERSION 3.20)

# If this is being built standalone, declare a project
if(CMAKE_SOURCE_DIR STREQUAL CMAKE_CURRENT_SOURCE_DIR)
    project(oxr_tracking_core VERSION 1.0.0 LANGUAGES CXX)
    set(CMAKE_CXX_STANDARD 17)
    set(CMAKE_CXX_STANDARD_REQUIRED ON)
endif()

# Core OpenXR tracking library (static for distribution)
add_library(oxr_tracking_core STATIC
    oxr_manager.cpp
    oxr_session.cpp
    oxr_handtracker.cpp
    oxr_headtracker.cpp
    inc/oxr/oxr_manager.hpp
    inc/oxr/oxr_session.hpp
    inc/oxr/oxr_handtracker.hpp
    inc/oxr/oxr_headtracker.hpp
)

target_include_directories(oxr_tracking_core
    INTERFACE
        $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}/inc>
        $<INSTALL_INTERFACE:include>
)

target_link_libraries(oxr_tracking_core
    PUBLIC
        OpenXR::headers
    PRIVATE
        OpenXR::openxr_loader
)

# Create alias for consistent naming
add_library(oxr_tracking::oxr_tracking_core ALIAS oxr_tracking_core)

# Optional: Install for distribution
install(TARGETS oxr_tracking_core
    ARCHIVE DESTINATION lib
    INCLUDES DESTINATION include
)

install(DIRECTORY inc/oxr
    DESTINATION include
)

