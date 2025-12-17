add_executable(ManusHandTrackerPrinter
  manus_hand_tracker_printer.cpp
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

