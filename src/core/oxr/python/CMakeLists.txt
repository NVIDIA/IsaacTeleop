# Python bindings using pybind11
# Use centralized Python version configuration from root CMakeLists.txt
include(${CMAKE_SOURCE_DIR}/cmake/SetupPython.cmake)

# Additional pybind11 compatibility variables
set(PYTHON_EXECUTABLE "${Python3_EXECUTABLE}" CACHE FILEPATH "Python executable for pybind11" FORCE)
set(PYTHON_INCLUDE_DIRS "${Python3_INCLUDE_DIRS}" CACHE PATH "Python include dirs for pybind11" FORCE)
set(PYTHON_LIBRARIES "${Python3_LIBRARIES}" CACHE FILEPATH "Python libraries for pybind11" FORCE)

# Try to find pybind11 installed on system
find_package(pybind11 CONFIG QUIET)

if(NOT pybind11_FOUND)
    # Use pybind11 from git submodule
    set(PYBIND11_DIR "${CMAKE_SOURCE_DIR}/deps/third_party/pybind11")
    
    if(NOT EXISTS "${PYBIND11_DIR}/CMakeLists.txt")
        message(FATAL_ERROR 
            "pybind11 submodule not found. Please initialize it with:\n"
            "  git submodule update --init --recursive")
    endif()
    
    add_subdirectory("${PYBIND11_DIR}" "${CMAKE_BINARY_DIR}/pybind11_oxr")
    message(STATUS "Using pybind11 from submodule: ${PYBIND11_DIR}")
endif()

# OXR module (OpenXR session)
pybind11_add_module(oxr_py
    oxr_bindings.cpp
)

target_link_libraries(oxr_py
    PRIVATE
        oxr_core
)

set_target_properties(oxr_py PROPERTIES
    OUTPUT_NAME "_oxr"
    LIBRARY_OUTPUT_DIRECTORY "${CMAKE_BINARY_DIR}/python_package/teleopcore/oxr"
)

