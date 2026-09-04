// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#pragma once

// Turning MuJoCo's error path into an exception, for the copy this module loads.
//
// `mju_user_error` is a plain global per libmujoco copy, so setting it through the user's
// `mujoco` wheel does not reach ours and ours does not reach theirs. With no handler the
// default ends in exit(EXIT_FAILURE); a handler that RETURNS is worse, because MuJoCo
// resumes on invalid state.

#include <functional>

namespace robot_twin
{

// Installs the hooks on this copy. Call once, at module init.
void install_mujoco_handlers();

// Runs `fn` with the error handler armed, and throws std::runtime_error naming `what`
// and MuJoCo's message if it fires.
//
// Recovery is a longjmp past MuJoCo's C frames, so `fn` must call MuJoCo and nothing
// else: anything with a destructor between here and the error is skipped, not unwound.
void guarded(const char* what, const std::function<void()>& fn);

} // namespace robot_twin
