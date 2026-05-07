// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#pragma once

// Includes <openxr/openxr_platform.h> with the platform-specific headers
// that its conditional sections need in scope. Use this everywhere
// instead of including openxr_platform.h directly — keeps the include
// order correct regardless of which compile defines a TU happens to
// inherit.
//
// Win32: openxr_platform.h's XR_USE_PLATFORM_WIN32 sections reference
// LARGE_INTEGER and IUnknown. These need <Windows.h> + <Unknwn.h> first;
// <Unknwn.h> is NOT pulled in by Windows.h when WIN32_LEAN_AND_MEAN is
// set (which oxr_utils enables transitively).
//
// TIMESPEC: openxr_platform.h's XR_USE_TIMESPEC section uses
// `struct timespec` without including <ctime>. Pull it in here.

#define XR_USE_GRAPHICS_API_VULKAN

#if defined(XR_USE_PLATFORM_WIN32)
#include <Unknwn.h>
#include <Windows.h>
#endif

#if defined(XR_USE_TIMESPEC)
#include <ctime>
#endif

#include <openxr/openxr_platform.h>
