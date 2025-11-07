# Python bindings using pybind11
# Use managed Python 3.10 from uv (matching the pyproject.toml requirement)
if(NOT Python3_EXECUTABLE)
    # Check if uv is available
    find_program(UV_EXECUTABLE uv)
    
    if(UV_EXECUTABLE)
        # First, ensure Python 3.10 is installed as a managed version
        message(STATUS "Ensuring Python 3.10 is installed via uv...")
        execute_process(
            COMMAND ${UV_EXECUTABLE} python install 3.10 --quiet
            OUTPUT_QUIET
            ERROR_QUIET
            RESULT_VARIABLE UV_INSTALL_RESULT
        )
        
        # Now find the managed Python 3.10
        execute_process(
            COMMAND ${UV_EXECUTABLE} python find 3.10
            OUTPUT_VARIABLE UV_PYTHON_PATH
            OUTPUT_STRIP_TRAILING_WHITESPACE
            ERROR_QUIET
            RESULT_VARIABLE UV_FIND_RESULT
        )
        
        if(UV_FIND_RESULT EQUAL 0 AND EXISTS "${UV_PYTHON_PATH}")
            set(Python3_EXECUTABLE "${UV_PYTHON_PATH}" CACHE FILEPATH "Path to Python3 executable" FORCE)
            message(STATUS "Using managed Python 3.10 from uv: ${Python3_EXECUTABLE}")
        else()
            message(WARNING "uv python find failed. Falling back to system Python 3.10")
            find_program(PYTHON310 NAMES python3.10)
            if(PYTHON310)
                set(Python3_EXECUTABLE "${PYTHON310}" CACHE FILEPATH "Path to Python3 executable" FORCE)
                message(STATUS "Using system Python 3.10: ${Python3_EXECUTABLE}")
            endif()
        endif()
    else()
        message(WARNING "uv not found. Falling back to system Python 3.10")
        find_program(PYTHON310 NAMES python3.10)
        if(PYTHON310)
            set(Python3_EXECUTABLE "${PYTHON310}" CACHE FILEPATH "Path to Python3 executable" FORCE)
            message(STATUS "Using system Python 3.10: ${Python3_EXECUTABLE}")
        endif()
    endif()
endif()

find_package(Python3 COMPONENTS Interpreter Development REQUIRED)
message(STATUS "Building Python bindings with: ${Python3_EXECUTABLE} (version ${Python3_VERSION})")

# Force pybind11 to use the same Python version and libraries
set(PYBIND11_PYTHON_VERSION "${Python3_VERSION}" CACHE STRING "Python version for pybind11" FORCE)
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
    
    add_subdirectory("${PYBIND11_DIR}" "${CMAKE_BINARY_DIR}/pybind11_xrio")
    message(STATUS "Using pybind11 from submodule: ${PYBIND11_DIR}")
endif()

# XRIO module (trackers and teleop session)
pybind11_add_module(xrio_py
    xrio_bindings.cpp
)

target_link_libraries(xrio_py
    PRIVATE
        xrio_core
)

set_target_properties(xrio_py PROPERTIES
    OUTPUT_NAME "_xrio"
    LIBRARY_OUTPUT_DIRECTORY "${CMAKE_BINARY_DIR}/python_package/teleopcore/xrio"
)

