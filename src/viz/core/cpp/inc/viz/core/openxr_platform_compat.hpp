// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#pragma once

// Self-contained <openxr/openxr_platform.h> wrapper. Use everywhere
// instead of including openxr_platform.h directly — its conditional
// sections reference types from headers that aren't always in scope,
// and clang-format's include-regroup can shuffle them out of order.
//
// Vulkan: XR_USE_GRAPHICS_API_VULKAN gates VkFormat / VkInstance /
// VkDevice refs. Pull vulkan.h in here so the wrapper is self-contained
// regardless of where each TU orders its includes.
//
// Win32: XR_USE_PLATFORM_WIN32 sections reference LARGE_INTEGER and
// IUnknown. <Unknwn.h> is NOT pulled in by Windows.h when
// WIN32_LEAN_AND_MEAN is set (which oxr_utils enables transitively).
//
// TIMESPEC: XR_USE_TIMESPEC section uses `struct timespec` without
// including <ctime>. Pull it in here.

#define XR_USE_GRAPHICS_API_VULKAN
#include <vulkan/vulkan.h>

#if defined(XR_USE_PLATFORM_WIN32)
#    include <Unknwn.h>
#    include <Windows.h>
#endif

#if defined(XR_USE_TIMESPEC)
#    include <ctime>
#endif

#include <openxr/openxr_platform.h>
