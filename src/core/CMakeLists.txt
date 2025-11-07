cmake_minimum_required(VERSION 3.20)
project(teleopcore_modules VERSION 1.0.0 LANGUAGES CXX)

# Options
option(BUILD_PYTHON_BINDINGS "Build Python bindings" ON)

# Build OXR library first (OXR session - no dependencies)
add_subdirectory(oxr)

# Build XRIO library (depends on OXR for types)
add_subdirectory(xrio)

# Python wheel packaging (combines both modules)
if(BUILD_PYTHON_BINDINGS)
    add_subdirectory(python)
endif()

