# ==============================================================================
# SetupPython.cmake
# ==============================================================================
# Centralizes Python executable discovery and configuration.
# Uses the TELEOPCORE_PYTHON_VERSION variable from root CMakeLists.txt.
#
# This module uses uv to install and find the managed Python version.
#
# Usage: include(cmake/SetupPython.cmake)
# ==============================================================================

if(NOT DEFINED TELEOPCORE_PYTHON_VERSION)
    message(FATAL_ERROR "TELEOPCORE_PYTHON_VERSION must be set before including SetupPython.cmake")
endif()

# Only run this logic if Python3_EXECUTABLE is not already set
if(NOT Python3_EXECUTABLE)
    # Check if uv is available
    find_program(UV_EXECUTABLE uv)

    if(UV_EXECUTABLE)
        # First, ensure the required Python version is installed as a managed version
        message(STATUS "Ensuring Python ${TELEOPCORE_PYTHON_VERSION} is installed via uv...")
        execute_process(
            COMMAND ${UV_EXECUTABLE} python install ${TELEOPCORE_PYTHON_VERSION} --quiet
            OUTPUT_QUIET
            ERROR_QUIET
            RESULT_VARIABLE UV_INSTALL_RESULT
        )

        # Now find the managed Python
        execute_process(
            COMMAND ${UV_EXECUTABLE} python find ${TELEOPCORE_PYTHON_VERSION}
            OUTPUT_VARIABLE UV_PYTHON_PATH
            OUTPUT_STRIP_TRAILING_WHITESPACE
            ERROR_QUIET
            RESULT_VARIABLE UV_FIND_RESULT
        )

        if(UV_FIND_RESULT EQUAL 0 AND EXISTS "${UV_PYTHON_PATH}")
            set(Python3_EXECUTABLE "${UV_PYTHON_PATH}" CACHE FILEPATH "Path to Python3 executable" FORCE)
            message(STATUS "Using managed Python ${TELEOPCORE_PYTHON_VERSION} from uv: ${Python3_EXECUTABLE}")
        else()
            message(FATAL_ERROR "Could not find managed Python ${TELEOPCORE_PYTHON_VERSION} with uv.")
        endif()
    else()
        message(FATAL_ERROR "Could not find managed Python ${TELEOPCORE_PYTHON_VERSION} with uv.")
    endif()
endif()

# Find Python using the executable we determined
find_package(Python3 REQUIRED COMPONENTS Interpreter Development)

message(STATUS "Building Python bindings with: ${Python3_EXECUTABLE} (version ${Python3_VERSION})")

# Force pybind11 to use the same Python version and libraries
set(PYBIND11_PYTHON_VERSION "${Python3_VERSION}" CACHE STRING "Python version for pybind11" FORCE)

