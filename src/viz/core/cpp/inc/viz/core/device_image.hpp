// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#pragma once

namespace viz
{

// Owning device-side 2D pixel buffer with CUDA-Vulkan interop. The
// symmetric counterpart to HostImage: HostImage owns CPU bytes,
// DeviceImage will own:
//   - VkImage / VkBuffer + VkDeviceMemory exported via
//     VK_KHR_external_memory_fd
//   - cudaExternalMemory_t imported from that fd, plus the CUDA device
//     pointer derived from it
//   - paired cudaExternalSemaphore_t / VkSemaphore for acquire / release
//     synchronization
//
// Returned by Televiz's mode-B submission path (acquire / release) when
// Televiz allocates the interop buffer for a layer to write into.
//
// Intentionally only forward-declared in this milestone — the
// implementation ships alongside CUDA-Vulkan interop. Callers may pass
// pointers / references to DeviceImage between modules but cannot
// instantiate one until then.
class DeviceImage;

} // namespace viz
