# ==============================================================================
# SetupPython.cmake
# ==============================================================================
# Centralizes Python executable discovery and configuration.
# Uses the TELEOPCORE_PYTHON_VERSION variable from root CMakeLists.txt.
#
# This module uses uv to install and find the managed Python version.
# It ALWAYS uses uv-managed Python, ignoring any venv or system Python.
#
# Usage: include(cmake/SetupPython.cmake)
# ==============================================================================

if(NOT DEFINED TELEOPCORE_PYTHON_VERSION)
    message(FATAL_ERROR "TELEOPCORE_PYTHON_VERSION must be set before including SetupPython.cmake")
endif()

# Guard to prevent multiple inclusions from overwriting our settings
if(NOT TELEOPCORE_PYTHON_CONFIGURED)
    # Unset any previously found Python to prevent interference from venvs
    unset(Python3_EXECUTABLE CACHE)
    unset(Python3_LIBRARY CACHE)
    unset(Python3_INCLUDE_DIR CACHE)
    unset(PYTHON_EXECUTABLE CACHE)

    # Check if uv is available
    find_program(UV_EXECUTABLE uv)

    if(NOT UV_EXECUTABLE)
        message(FATAL_ERROR "uv not found. Please install uv: curl -LsSf https://astral.sh/uv/install.sh | sh")
    endif()

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

    if(NOT UV_FIND_RESULT EQUAL 0 OR NOT EXISTS "${UV_PYTHON_PATH}")
        message(FATAL_ERROR "Could not find managed Python ${TELEOPCORE_PYTHON_VERSION} with uv.")
    endif()

    # Force CMake to use our specific Python
    set(Python3_EXECUTABLE "${UV_PYTHON_PATH}" CACHE FILEPATH "Path to Python3 executable" FORCE)
    set(PYTHON_EXECUTABLE "${UV_PYTHON_PATH}" CACHE FILEPATH "Path to Python executable" FORCE)
    message(STATUS "Using managed Python ${TELEOPCORE_PYTHON_VERSION} from uv: ${Python3_EXECUTABLE}")

    # Find Python using the executable we determined
    # Use EXACT to prevent CMake from finding a different version
    find_package(Python3 ${TELEOPCORE_PYTHON_VERSION} EXACT REQUIRED COMPONENTS Interpreter Development)

    message(STATUS "Building Python bindings with: ${Python3_EXECUTABLE} (version ${Python3_VERSION})")

    # Force pybind11 to use the same Python version and libraries
    set(PYBIND11_PYTHON_VERSION "${Python3_VERSION}" CACHE STRING "Python version for pybind11" FORCE)
    set(PYBIND11_PYTHON_INCLUDE_DIR "${Python3_INCLUDE_DIRS}" CACHE STRING "Python include dir for pybind11" FORCE)
    set(PYBIND11_PYTHON_LIBRARIES "${Python3_LIBRARIES}" CACHE STRING "Python libraries for pybind11" FORCE)
    
    # Set legacy variables for compatibility (important for some find modules)
    set(PYTHON_INCLUDE_DIRS "${Python3_INCLUDE_DIRS}" CACHE PATH "Python include dirs" FORCE)
    set(PYTHON_LIBRARIES "${Python3_LIBRARIES}" CACHE FILEPATH "Python libraries" FORCE)

    # Mark as configured to prevent re-running
    set(TELEOPCORE_PYTHON_CONFIGURED TRUE CACHE INTERNAL "Python configuration completed")
endif()

