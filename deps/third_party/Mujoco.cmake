# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
#
# Makes the MuJoCo fetched beside this file private, so a user may `pip install mujoco` at
# any version, or none, and never collide with ours. Three things hold that up, none
# optional:
#
#   OUTPUT_NAME   a private SONAME. The mujoco wheel's extensions carry a DT_NEEDED on
#                 libmujoco.so.3.x, and the loader satisfies it from whatever is already
#                 loaded under that SONAME -- so an unrenamed copy of ours, loaded first,
#                 answers the user's own `import mujoco`.
#   -Bsymbolic    libmujoco's cross-references bind to itself rather than to whatever copy
#                 is in the global scope. Not -Bsymbolic-functions: mju_user_error and
#                 mju_user_warning are data, and libmujoco reads them.
#   dlopen/dlsym  src/viz/robot_twin/cpp/mj_api.cpp resolves MuJoCo at import instead of
#                 linking it, so the extension has no undefined mj* for a foreign
#                 libmujoco to answer.
#
# Do not replace the dlopen with a plain link: the wrong libmujoco answering is silent.

set_target_properties(mujoco PROPERTIES OUTPUT_NAME isaacteleop_mujoco)
# Upstream's VERSION would make libisaacteleop_mujoco.so a symlink to ...so.3.11.0, and
# wheels do not carry symlinks. Unset with no value, which REMOVES the property; "" leaves
# it set and names the library `libisaacteleop_mujoco.so.`.
set_property(TARGET mujoco PROPERTY VERSION)
set_property(TARGET mujoco PROPERTY SOVERSION)
set_property(TARGET mujoco APPEND PROPERTY LINK_OPTIONS "-Wl,-Bsymbolic")

# Set up an extension that reaches MuJoCo through mj_api.cpp: headers to compile against,
# libisaacteleop_mujoco.so staged beside the module for the dlopen to find, and a dynamic
# symbol table holding nothing but the entry point. `module_name` is the importable name,
# whose PyInit_ symbol is the one export.
function(isaacteleop_link_mujoco target module_name)
    # Headers only. Nothing links MuJoCo, so add_dependencies supplies the build order a
    # link line would otherwise have implied.
    target_include_directories(${target} PRIVATE
        $<TARGET_PROPERTY:mujoco,INTERFACE_INCLUDE_DIRECTORIES>)
    add_dependencies(${target} mujoco)

    # mj_api.cpp opens it by this module's own directory, so the copy has to be there --
    # in the build tree for ctest, and in the staged python_package that install(DIRECTORY)
    # turns into the wheel.
    add_custom_command(TARGET ${target} POST_BUILD
        COMMAND ${CMAKE_COMMAND} -E copy_if_different
                "$<TARGET_FILE:mujoco>" "$<TARGET_FILE_DIR:${target}>"
        COMMENT "Staging $<TARGET_FILE_NAME:mujoco> beside $<TARGET_FILE_NAME:${target}>")

    # The wheel redistributes the binary above, so Apache-2.0 section 4 requires its
    # licence to travel with it. Upstream ships no top-level NOTICE; if one ever appears,
    # it has to be staged here too. MUJOCO_LICENSE is what pyproject.toml names.
    add_custom_command(TARGET ${target} POST_BUILD
        COMMAND ${CMAKE_COMMAND} -E copy_if_different
                "${mujoco_SOURCE_DIR}/LICENSE" "$<TARGET_FILE_DIR:${target}>/MUJOCO_LICENSE"
        COMMENT "Staging MuJoCo's LICENSE beside $<TARGET_FILE_NAME:mujoco>")

    # A whitelist, so it covers what pybind11's -fvisibility=hidden misses: symbols from
    # static archives (cudart_static) and the typeinfo pybind11 emits for the mjt* enums.
    # Measured on robot_twin_py: 1 export, against 11 for -Wl,--exclude-libs,ALL alone.
    set(_version_script "${CMAKE_CURRENT_BINARY_DIR}/${target}_exports.map")
    file(GENERATE OUTPUT "${_version_script}"
         CONTENT "{ global: PyInit_${module_name}; local: *; };\n")
    target_link_options(${target} PRIVATE "-Wl,--version-script,${_version_script}")
    set_property(TARGET ${target} APPEND PROPERTY LINK_DEPENDS "${_version_script}")
endfunction()
