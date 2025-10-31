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
            # Verify it's a managed Python (not system Python)
            execute_process(
                COMMAND ${UV_EXECUTABLE} python dir
                OUTPUT_VARIABLE UV_PYTHON_DIR
                OUTPUT_STRIP_TRAILING_WHITESPACE
                ERROR_QUIET
            )
            
            string(FIND "${UV_PYTHON_PATH}" "${UV_PYTHON_DIR}" IS_MANAGED)
            if(IS_MANAGED GREATER -1)
                set(Python3_EXECUTABLE "${UV_PYTHON_PATH}" CACHE FILEPATH "Path to Python3 executable" FORCE)
                message(STATUS "Using managed Python 3.10 from uv: ${Python3_EXECUTABLE}")
            else()
                message(WARNING "uv found system Python instead of managed. Ensure 'uv python install 3.10' was successful.")
                set(Python3_EXECUTABLE "${UV_PYTHON_PATH}" CACHE FILEPATH "Path to Python3 executable" FORCE)
                message(STATUS "Using Python from uv: ${Python3_EXECUTABLE}")
            endif()
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
    
    add_subdirectory("${PYBIND11_DIR}" "${CMAKE_BINARY_DIR}/pybind11")
    message(STATUS "Using pybind11 from submodule: ${PYBIND11_DIR}")
endif()

# Modular tracking API module
pybind11_add_module(oxr_tracking_py
    oxr_python_bindings_modular.cpp
)

target_link_libraries(oxr_tracking_py
    PRIVATE
        oxr_tracking_core
)

set_target_properties(oxr_tracking_py PROPERTIES
    OUTPUT_NAME "oxr_tracking"
    LIBRARY_OUTPUT_DIRECTORY "${CMAKE_BINARY_DIR}/python_package/oxr_tracking"
)

# Create Python package structure for building wheel
add_custom_command(TARGET oxr_tracking_py POST_BUILD
    COMMAND ${CMAKE_COMMAND} -E make_directory "${CMAKE_BINARY_DIR}/python_package/oxr_tracking"
    COMMAND ${CMAKE_COMMAND} -E copy $<TARGET_FILE:oxr_tracking_py> "${CMAKE_BINARY_DIR}/python_package/oxr_tracking/"
    COMMAND ${CMAKE_COMMAND} -E copy "${CMAKE_CURRENT_SOURCE_DIR}/__init__.py" "${CMAKE_BINARY_DIR}/python_package/oxr_tracking/"
    COMMAND ${CMAKE_COMMAND} -E copy "${CMAKE_CURRENT_SOURCE_DIR}/pyproject.toml" "${CMAKE_BINARY_DIR}/python_package/"
    COMMAND ${CMAKE_COMMAND} -E copy "${CMAKE_CURRENT_SOURCE_DIR}/../README.md" "${CMAKE_BINARY_DIR}/python_package/" || true
    COMMENT "Preparing Python package structure"
)

# Custom target to build the wheel using uv
add_custom_target(python_wheel ALL
    COMMAND ${CMAKE_COMMAND} -E echo "Building Python wheel with uv..."
    COMMAND ${CMAKE_COMMAND} -E make_directory "${CMAKE_BINARY_DIR}/wheels"
    COMMAND uv build --wheel --out-dir "${CMAKE_BINARY_DIR}/wheels" "${CMAKE_BINARY_DIR}/python_package" || 
            ${Python3_EXECUTABLE} -m build --wheel --outdir "${CMAKE_BINARY_DIR}/wheels" "${CMAKE_BINARY_DIR}/python_package"
    DEPENDS oxr_tracking_py
    WORKING_DIRECTORY "${CMAKE_BINARY_DIR}"
    COMMENT "Building Python wheel with uv (fallback to python -m build)"
)

# Install the wheel
install(DIRECTORY "${CMAKE_BINARY_DIR}/wheels/"
    DESTINATION wheels
    FILES_MATCHING PATTERN "*.whl"
)

