# Option to help runtime resolution from the build tree by adding the Manus SDK
# library directory to BUILD_RPATH (useful when not copying the SDK runtime).
option(MANUS_ADD_SDK_TO_BUILD_RPATH "Add Manus SDK lib dir to BUILD_RPATH for plugin and tools" ON)

# Resolve Manus SDK root. Prefer environment variable if provided, otherwise default to bundled src/plugins/manus/ManusSDK
if(NOT DEFINED MANUS_SDK_ROOT AND DEFINED ENV{MANUS_SDK_ROOT})
  set(MANUS_SDK_ROOT "$ENV{MANUS_SDK_ROOT}" CACHE PATH "Path to Manus SDK root containing include/ and lib/" FORCE)
else()
  set(MANUS_SDK_ROOT "${CMAKE_SOURCE_DIR}/ManusSDK" CACHE PATH "Path to Manus SDK root containing include/ and lib/")
endif()

set(MANUS_SDK_INCLUDE_DIR "${MANUS_SDK_ROOT}/include" CACHE PATH "Manus SDK include path" FORCE)

# Auto-detect best library directory (supports lib or lib64)
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

# Validate Manus SDK
if(NOT EXISTS "${MANUS_SDK_INCLUDE_DIR}/ManusSDK.h")
  message(FATAL_ERROR "Manus SDK headers not found in ${MANUS_SDK_INCLUDE_DIR}. Set MANUS_SDK_ROOT or MANUS_SDK_INCLUDE_DIR.")
endif()
if(NOT EXISTS "${MANUS_SDK_LIBRARY_DIR}/libManusSDK.so")
  if(NOT EXISTS "${MANUS_SDK_LIBRARY_DIR}/libManusSDK_Integrated.so")
    message(FATAL_ERROR "Manus SDK libraries not found in ${MANUS_SDK_LIBRARY_DIR}. Expected libManusSDK.so or libManusSDK_Integrated.so")
  endif()
endif()

# Prefer the Integrated library when available
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
  message(FATAL_ERROR "No Manus SDK shared library found under ${MANUS_SDK_LIBRARY_DIR}")
endif()

# Create imported library target for Manus SDK
# Note: The Manus SDK library doesn't have a SONAME, so we need to use IMPORTED_NO_SONAME
# to prevent CMake from embedding the full path in the NEEDED entry
add_library(ManusSDK::ManusSDK SHARED IMPORTED)

# Extract just the library filename for SONAME
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
)

target_include_directories(isaac_manus_plugin
  PRIVATE
    $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}>
  PUBLIC
    $<BUILD_INTERFACE:${MANUS_SDK_INCLUDE_DIR}>
)

target_link_libraries(isaac_manus_plugin
  PRIVATE
    ManusSDK::ManusSDK
)

set_target_properties(isaac_manus_plugin PROPERTIES
  OUTPUT_NAME IsaacTeleopPluginsManus
  LIBRARY_OUTPUT_DIRECTORY "${CMAKE_LIBRARY_OUTPUT_DIRECTORY}"
  CXX_VISIBILITY_PRESET hidden
  VISIBILITY_INLINES_HIDDEN YES
  BUILD_WITH_INSTALL_RPATH NO
  SKIP_BUILD_RPATH NO
)

# Compute a robust BUILD_RPATH. Always include $ORIGIN and $ORIGIN/../lib to
# find our own shared libraries. Optionally include the Manus SDK lib path to
# simplify running from the build tree on systems without global SDK install.
set(_ISAAC_MANUS_BASE_BUILD_RPATH "$ORIGIN;$ORIGIN/../lib")
set(_ISAAC_MANUS_EFFECTIVE_BUILD_RPATH "${_ISAAC_MANUS_BASE_BUILD_RPATH}")
if(MANUS_ADD_SDK_TO_BUILD_RPATH)
  list(APPEND _ISAAC_MANUS_EFFECTIVE_BUILD_RPATH "${MANUS_SDK_LIBRARY_DIR}")
endif()
list(JOIN _ISAAC_MANUS_EFFECTIVE_BUILD_RPATH ";" _ISAAC_MANUS_EFFECTIVE_BUILD_RPATH_STR)
set_target_properties(isaac_manus_plugin PROPERTIES
  BUILD_RPATH "${_ISAAC_MANUS_EFFECTIVE_BUILD_RPATH_STR}"
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
  # Allow running from build dir; resolve libs next to the exe
  SKIP_BUILD_RPATH NO
)

# Apply the same effective BUILD_RPATH to the CLI for consistency
set_target_properties(ManusHandTrackerPrinter PROPERTIES
  BUILD_RPATH "${_ISAAC_MANUS_EFFECTIVE_BUILD_RPATH_STR}"
)

# Put exe in bin so $ORIGIN/../lib points to our shared libs
set_target_properties(ManusHandTrackerPrinter PROPERTIES RUNTIME_OUTPUT_DIRECTORY "${CMAKE_BINARY_DIR}/bin")
