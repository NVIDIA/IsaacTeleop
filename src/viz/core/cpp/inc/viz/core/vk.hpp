// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#pragma once

// Project-wide vulkan-hpp + vk::raii include header.
//
// Conventions for Televiz Vulkan code:
//   * Owned handles use vk::raii::* (Instance, Device, Image, Semaphore, ...)
//   * pNext chains use vk::StructureChain<Outer, Inner1, Inner2, ...>
//   * Initialize structs with C++20 designated initializers
//     (`vk::ImageCreateInfo{.imageType = ..., .format = ..., ...}`)
//   * Extract raw handles via *handle_ ONLY at deliberate interop
//     boundaries (CUDA external memory FD, XrGraphicsBindingVulkanKHR).
//     Mark such sites with a comment so they read as boundary code.
//
// We use the default static dispatch for vulkan-hpp; vk::raii types
// own their dispatcher automatically — no VULKAN_HPP_DEFAULT_DISPATCHER
// initialization needed.
//
// VULKAN_HPP_NO_CONSTRUCTORS is defined as a project-wide compile
// flag in viz_core's CMakeLists (PUBLIC propagation), not here —
// otherwise the macro would only take effect for TUs that happen to
// include this header before vulkan.hpp. The compile flag enforces
// it everywhere, removing vulkan-hpp's hand-written constructors so
// structs are aggregates and C++20 designated initializers work
// (`vk::ImageCreateInfo{.format = ..., ...}`).

#include <vulkan/vulkan.hpp>
#include <vulkan/vulkan_raii.hpp>
