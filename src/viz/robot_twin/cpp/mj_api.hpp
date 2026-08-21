// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#pragma once

// The MuJoCo entry points this module calls (mj_functions.inc), resolved at import
// against the libisaacteleop_mujoco.so that ships beside this extension.
//
// Nothing links MuJoCo, and that is the isolation: an undefined mj* symbol here would
// resolve through the global scope, which the loader searches first, so a user's own
// libmujoco sitting in it would answer instead of ours -- silently, and with a different
// mjModel layout. See cmake/Mujoco.cmake.

#include <mujoco/mujoco.h>

namespace robot_twin
{
namespace mujoco
{

#define ROBOT_TWIN_MJ_FN(name) extern decltype(::name)* name;
#define ROBOT_TWIN_MJ_VAR(name) extern decltype(::name)* name;
#include "mj_functions.inc"
#undef ROBOT_TWIN_MJ_FN
#undef ROBOT_TWIN_MJ_VAR

// Resolves every entry point above. Idempotent. Throws naming the first symbol it cannot
// find, or the library it cannot open.
//
// The module initialiser calls it, and that is the only way into this extension, so no
// caller can reach a null pointer.
void load();

} // namespace mujoco
} // namespace robot_twin
