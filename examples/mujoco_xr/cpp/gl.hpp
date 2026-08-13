// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#pragma once

// The OpenGL entry points this module calls (gl_functions.inc), resolved at
// runtime against the context `mujoco.GLContext` created. Nothing links libGL:
// glcorearb.h supplies the enums and PFNGL...PROC typedefs but declares no
// function, GL_GLEXT_PROTOTYPES being undefined. It costs no build dependency
// either -- it ships beside <GL/gl.h>, which cuda_gl_interop.h always includes.

#include <GL/glcorearb.h>

namespace mujoco_xr
{
namespace gl
{

#define MUJOCO_XR_GL(name, upper) extern PFNGL##upper##PROC name;
#include "gl_functions.inc"
#undef MUJOCO_XR_GL

// Resolves every entry point above against the CURRENT context. Idempotent.
// Throws naming the first unresolvable one, which means either no current
// context or one older than OpenGL 3.3.
void load();

// Whether load() succeeded. Teardown paths need it: they are reached with
// nothing loaded when construction threw.
bool loaded();

// Throws naming `what` if glGetError() is set. Drains the queue either way, so
// one stale error cannot fail every later check.
void check(const char* what);

} // namespace gl
} // namespace mujoco_xr
