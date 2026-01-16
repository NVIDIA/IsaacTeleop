add_library(manus_plugin_core SHARED
  manus_hand_tracking_plugin.cpp
  ${MANUS_PLUGIN_INC_DIR}/core/manus_hand_tracking_plugin.hpp
)

target_include_directories(manus_plugin_core
  PUBLIC
    $<BUILD_INTERFACE:${MANUS_PLUGIN_INC_DIR}>
)

target_link_libraries(manus_plugin_core
  PUBLIC
    ManusSDK::ManusSDK
    Teleop::plugin_utils
    OpenXR::openxr_loader
    oxr::oxr_core
  PRIVATE
    oxr::oxr_utils
    Teleop::openxr_extensions
)

set_target_properties(manus_plugin_core PROPERTIES
  OUTPUT_NAME IsaacTeleopPluginsManus
  LIBRARY_OUTPUT_DIRECTORY "${CMAKE_LIBRARY_OUTPUT_DIRECTORY}"
  CXX_VISIBILITY_PRESET hidden
  VISIBILITY_INLINES_HIDDEN YES
  BUILD_WITH_INSTALL_RPATH NO
  SKIP_BUILD_RPATH NO
  BUILD_RPATH "${_ISAAC_MANUS_EFFECTIVE_BUILD_RPATH_STR}"
  INSTALL_RPATH "$ORIGIN"
)

install(TARGETS manus_plugin_core
    LIBRARY DESTINATION ${CMAKE_INSTALL_LIBDIR}
    RUNTIME DESTINATION ${CMAKE_INSTALL_BINDIR}
)

