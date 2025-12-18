add_executable(manus_hand_tracker_printer
  manus_hand_tracker_printer.cpp
)

target_link_libraries(manus_hand_tracker_printer
  PRIVATE
    manus_plugin_core
)

set_target_properties(manus_hand_tracker_printer PROPERTIES
  CXX_VISIBILITY_PRESET hidden
  VISIBILITY_INLINES_HIDDEN YES
  BUILD_WITH_INSTALL_RPATH NO
  SKIP_BUILD_RPATH NO
  BUILD_RPATH "${_ISAAC_MANUS_EFFECTIVE_BUILD_RPATH_STR}"
  RUNTIME_OUTPUT_DIRECTORY "${CMAKE_BINARY_DIR}/bin"
)

