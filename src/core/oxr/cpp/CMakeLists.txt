cmake_minimum_required(VERSION 3.20)

# If this is being built standalone, declare a project
if(CMAKE_SOURCE_DIR STREQUAL CMAKE_CURRENT_SOURCE_DIR)
    project(oxr_tracking_core VERSION 1.0.0 LANGUAGES CXX)
    set(CMAKE_CXX_STANDARD 17)
    set(CMAKE_CXX_STANDARD_REQUIRED ON)
endif()

# Find OpenXR if not already found
if(NOT TARGET OpenXR::OpenXR)
    find_package(PkgConfig QUIET)
    if(PKG_CONFIG_FOUND)
        pkg_check_modules(PC_OpenXR QUIET openxr)
    endif()
    
    find_path(OpenXR_INCLUDE_DIR
        NAMES openxr/openxr.h
        PATHS ${PC_OpenXR_INCLUDE_DIRS} /usr/include /usr/local/include
        PATH_SUFFIXES include
    )
    
    find_library(OpenXR_LIBRARY
        NAMES openxr_loader libopenxr_loader
        PATHS ${PC_OpenXR_LIBRARY_DIRS} /usr/lib /usr/local/lib 
              /usr/lib/x86_64-linux-gnu /usr/lib/aarch64-linux-gnu
        PATH_SUFFIXES lib lib64
    )
    
    include(FindPackageHandleStandardArgs)
    find_package_handle_standard_args(OpenXR
        REQUIRED_VARS OpenXR_LIBRARY OpenXR_INCLUDE_DIR
    )
    
    if(OpenXR_FOUND)
        add_library(OpenXR::OpenXR UNKNOWN IMPORTED)
        set_target_properties(OpenXR::OpenXR PROPERTIES
            IMPORTED_LOCATION "${OpenXR_LIBRARY}"
            INTERFACE_INCLUDE_DIRECTORIES "${OpenXR_INCLUDE_DIR}"
        )
        message(STATUS "Found OpenXR: ${OpenXR_LIBRARY}")
        message(STATUS "  Include: ${OpenXR_INCLUDE_DIR}")
    endif()
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
        OpenXR::OpenXR
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

