add_library(isaac_manus_plugin SHARED
  manus_hand_tracking_plugin.cpp
  manus_hand_tracking_plugin.hpp
)

target_include_directories(isaac_manus_plugin
  PRIVATE
    $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}>
  PUBLIC
    $<BUILD_INTERFACE:${CMAKE_CURRENT_SOURCE_DIR}>
    $<BUILD_INTERFACE:${MANUS_SDK_INCLUDE_DIR}>
)

target_link_libraries(isaac_manus_plugin
  PUBLIC
    ManusSDK::ManusSDK
    Teleop::plugin_utils
    OpenXR::openxr_loader
    Teleop::openxr_extensions
)

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

install(TARGETS isaac_manus_plugin
    LIBRARY DESTINATION ${CMAKE_INSTALL_LIBDIR}
    RUNTIME DESTINATION ${CMAKE_INSTALL_BINDIR}
)

