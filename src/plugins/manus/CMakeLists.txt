# SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

include(GNUInstallDirs)

option(MANUS_ADD_SDK_TO_BUILD_RPATH "Add Manus SDK lib dir to BUILD_RPATH for plugin and tools" ON)

if(NOT DEFINED MANUS_SDK_ROOT AND DEFINED ENV{MANUS_SDK_ROOT})
  set(MANUS_SDK_ROOT "$ENV{MANUS_SDK_ROOT}" CACHE PATH "Path to Manus SDK root containing include/ and lib/" FORCE)
else()
  set(MANUS_SDK_ROOT "${CMAKE_SOURCE_DIR}/ManusSDK" CACHE PATH "Path to Manus SDK root containing include/ and lib/")
endif()

set(MANUS_SDK_INCLUDE_DIR "${MANUS_SDK_ROOT}/include" CACHE PATH "Manus SDK include path" FORCE)

set(_MANUS_LIBDIR_CANDIDATES
  "${MANUS_SDK_ROOT}/lib"
  "${MANUS_SDK_ROOT}/lib64"
)
set(_MANUS_LIBDIR "")
foreach(_cand IN LISTS _MANUS_LIBDIR_CANDIDATES)
  if(EXISTS "${_cand}")
    set(_MANUS_LIBDIR "${_cand}")
    break()
  endif()
endforeach()
if(NOT _MANUS_LIBDIR)
  set(_MANUS_LIBDIR "${MANUS_SDK_ROOT}/lib")
endif()
set(MANUS_SDK_LIBRARY_DIR "${_MANUS_LIBDIR}" CACHE PATH "Manus SDK library path" FORCE)

if(NOT EXISTS "${MANUS_SDK_INCLUDE_DIR}/ManusSDK.h")
  message(STATUS "Manus SDK headers not found in ${MANUS_SDK_INCLUDE_DIR}. Skipping Manus plugin build.")
  return()
endif()
if(NOT EXISTS "${MANUS_SDK_LIBRARY_DIR}/libManusSDK.so")
  if(NOT EXISTS "${MANUS_SDK_LIBRARY_DIR}/libManusSDK_Integrated.so")
    message(STATUS "Manus SDK libraries not found in ${MANUS_SDK_LIBRARY_DIR}. Skipping Manus plugin build.")
    return()
  endif()
endif()

set(_MANUS_CANDIDATES
  "${MANUS_SDK_LIBRARY_DIR}/libManusSDK_Integrated.so"
  "${MANUS_SDK_LIBRARY_DIR}/libManusSDK.so"
)
set(_MANUS_LIB "")
foreach(_cand IN LISTS _MANUS_CANDIDATES)
  if(EXISTS "${_cand}")
    set(_MANUS_LIB "${_cand}")
    break()
  endif()
endforeach()
if(NOT _MANUS_LIB)
  message(STATUS "No Manus SDK shared library found under ${MANUS_SDK_LIBRARY_DIR}. Skipping Manus plugin build.")
  return()
endif()

# Create imported library target for Manus SDK
# Note: The Manus SDK library doesn't have a SONAME, so we need to use IMPORTED_NO_SONAME
add_library(ManusSDK::ManusSDK SHARED IMPORTED)

get_filename_component(_MANUS_LIB_NAME "${_MANUS_LIB}" NAME)

set_target_properties(ManusSDK::ManusSDK PROPERTIES
  IMPORTED_LOCATION "${_MANUS_LIB}"
  IMPORTED_SONAME "${_MANUS_LIB_NAME}"
  IMPORTED_NO_SONAME TRUE
  INTERFACE_INCLUDE_DIRECTORIES "${MANUS_SDK_INCLUDE_DIR}"
)

add_library(isaac_manus_plugin SHARED
  ManusHandTrackingPlugin.cpp
  ManusHandTrackingPlugin.h
  hand_injector.cpp
  hand_injector.hpp
  session.cpp
  session.hpp
  controllers.cpp
  controllers.hpp
)

find_package(OpenXR REQUIRED)

target_include_directories(isaac_manus_plugin
  PRIVATE
    $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}>
  PUBLIC
    $<BUILD_INTERFACE:${MANUS_SDK_INCLUDE_DIR}>
)

target_link_libraries(isaac_manus_plugin
  PUBLIC
    ManusSDK::ManusSDK
    OpenXR::openxr_loader
)

set(_ISAAC_MANUS_BASE_BUILD_RPATH "$ORIGIN;$ORIGIN/../lib")
set(_ISAAC_MANUS_EFFECTIVE_BUILD_RPATH "${_ISAAC_MANUS_BASE_BUILD_RPATH}")
if(MANUS_ADD_SDK_TO_BUILD_RPATH)
  list(APPEND _ISAAC_MANUS_EFFECTIVE_BUILD_RPATH "${MANUS_SDK_LIBRARY_DIR}")
endif()
list(JOIN _ISAAC_MANUS_EFFECTIVE_BUILD_RPATH ";" _ISAAC_MANUS_EFFECTIVE_BUILD_RPATH_STR)

set_target_properties(isaac_manus_plugin PROPERTIES
  OUTPUT_NAME IsaacTeleopPluginsManus
  LIBRARY_OUTPUT_DIRECTORY "${CMAKE_LIBRARY_OUTPUT_DIRECTORY}"
  CXX_VISIBILITY_PRESET hidden
  VISIBILITY_INLINES_HIDDEN YES
  BUILD_WITH_INSTALL_RPATH NO
  SKIP_BUILD_RPATH NO
  BUILD_RPATH "${_ISAAC_MANUS_EFFECTIVE_BUILD_RPATH_STR}"
  INSTALL_RPATH "$ORIGIN"
)

add_library(isaac::manus_plugin ALIAS isaac_manus_plugin)

# Sample CLI tool to print hand tracker output
add_executable(ManusHandTrackerPrinter
  ManusHandTrackerPrinter.cpp
)

target_include_directories(ManusHandTrackerPrinter
  PRIVATE
    ${CMAKE_CURRENT_SOURCE_DIR}
    ${MANUS_SDK_INCLUDE_DIR}
)

target_link_libraries(ManusHandTrackerPrinter
  PRIVATE
    isaac::manus_plugin
)

set_target_properties(ManusHandTrackerPrinter PROPERTIES
  CXX_VISIBILITY_PRESET hidden
  VISIBILITY_INLINES_HIDDEN YES
  BUILD_WITH_INSTALL_RPATH NO
  SKIP_BUILD_RPATH NO
  BUILD_RPATH "${_ISAAC_MANUS_EFFECTIVE_BUILD_RPATH_STR}"
  RUNTIME_OUTPUT_DIRECTORY "${CMAKE_BINARY_DIR}/bin"
)

# Main plugin executable
add_executable(manus_hand_plugin
  main.cpp
)

target_link_libraries(manus_hand_plugin
  PRIVATE
    isaac_manus_plugin
)

set_target_properties(manus_hand_plugin PROPERTIES
  CXX_VISIBILITY_PRESET hidden
  VISIBILITY_INLINES_HIDDEN YES
  BUILD_WITH_INSTALL_RPATH NO
  SKIP_BUILD_RPATH NO
  BUILD_RPATH "${_ISAAC_MANUS_EFFECTIVE_BUILD_RPATH_STR}"
  INSTALL_RPATH "$ORIGIN/../../${CMAKE_INSTALL_LIBDIR}"
)

# Installation
install(TARGETS manus_hand_plugin
    RUNTIME DESTINATION plugins/manus
)

install(FILES plugin.yaml README.md
    DESTINATION plugins/manus
)

install(TARGETS isaac_manus_plugin
    LIBRARY DESTINATION ${CMAKE_INSTALL_LIBDIR}
    RUNTIME DESTINATION ${CMAKE_INSTALL_BINDIR}
)

# Install Manus SDK shared library
install(FILES "${_MANUS_LIB}"
    DESTINATION ${CMAKE_INSTALL_LIBDIR}
)
