cmake_minimum_required(VERSION 3.22)

project(ManusPluginTests)

include(FetchContent)
FetchContent_Declare(
  Catch2
  GIT_REPOSITORY https://github.com/catchorg/Catch2.git
  GIT_TAG        v3.4.0
)
FetchContent_MakeAvailable(Catch2)

# Find Catch2 (provided by FetchContent)
# find_package(Catch2 3 REQUIRED) # Not needed with FetchContent usually if it adds targets

# Mock headers include path
set(MOCK_INCLUDE_DIR "${CMAKE_CURRENT_SOURCE_DIR}/mock_headers")
set(MOCK_PLUGIN_UTILS_DIR "${CMAKE_CURRENT_SOURCE_DIR}/mock_headers/plugin_utils")
set(MOCK_MANUS_SDK_DIR "${CMAKE_CURRENT_SOURCE_DIR}/mock_headers/ManusSDK/include")
set(MOCK_OPENXR_DIR "${CMAKE_CURRENT_SOURCE_DIR}/mock_headers/openxr")

add_executable(manus_tests
    test_manus_plugin.cpp
    mock_env.cpp
    ../core/manus_hand_tracking_plugin.cpp
)

target_include_directories(manus_tests PRIVATE
    ${MOCK_INCLUDE_DIR}
    ${MOCK_MANUS_SDK_DIR}
    ${MOCK_INCLUDE_DIR} # For openxr
    ../core
)

# We need to make sure our mocks are found BEFORE any system or other includes
# that might contain real headers.
# Specifically, we need plugin_utils headers to be found in our mock dir.
# The source file uses #include <plugin_utils/session.hpp>
# So we need "mock_headers" to be in include path, and it contains "plugin_utils/session.hpp"

target_link_libraries(manus_tests PRIVATE
    Catch2::Catch2
)

# Compiler options
target_compile_features(manus_tests PRIVATE cxx_std_17)

