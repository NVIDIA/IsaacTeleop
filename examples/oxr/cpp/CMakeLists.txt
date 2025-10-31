cmake_minimum_required(VERSION 3.20)

# Find the library if not building from top-level
if(NOT TARGET oxr_tracking::oxr_tracking_core)
    find_package(oxr_tracking_core REQUIRED)
endif()

# C++ session sharing example
add_executable(oxr_session_sharing
    oxr_session_sharing.cpp
)

target_link_libraries(oxr_session_sharing
    PRIVATE
        oxr_tracking::oxr_tracking_core
)

# Set C++ standard for this target only
set_target_properties(oxr_session_sharing PROPERTIES
    CXX_STANDARD 17
    CXX_STANDARD_REQUIRED ON
)

# Install
install(TARGETS oxr_session_sharing
    RUNTIME DESTINATION examples/oxr/cpp
)
