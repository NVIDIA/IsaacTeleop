// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#pragma once

#include <viz/core/render_target.hpp>
#include <viz/core/viz_types.hpp>
#include <viz/layers/layer_base.hpp>
#include <vulkan/vulkan.h>

#include <atomic>
#include <cstdint>
#include <stdexcept>
#include <string>
#include <vector>

namespace viz::testing
{

// Test fixture layer that throws from record() on a configurable
// schedule. Used to verify the compositor / session recover correctly
// from layer-side exceptions (no fence deadlocks, no leaked Vulkan
// state, layer registry intact).
//
// `throw_after_n_calls` = 0 means "throw on every call".
// `throw_after_n_calls` = N (>= 1) means "succeed N times, then throw".
// Once it has thrown, it keeps throwing on every subsequent call unless
// reset via reset_call_count().
class ThrowingLayer final : public LayerBase
{
public:
    struct Config
    {
        uint32_t throw_after_n_calls = 0; // 0 = throw immediately
        std::string what = "ThrowingLayer: intentional test failure";
        std::string name = "ThrowingLayer";
    };

    explicit ThrowingLayer(Config config) : LayerBase(config.name), config_(std::move(config))
    {
    }

    void record(VkCommandBuffer /*cmd*/,
                const std::vector<viz::ViewInfo>& /*views*/,
                const viz::RenderTarget& /*target*/) override
    {
        const uint32_t prior = call_count_.fetch_add(1);
        if (prior >= config_.throw_after_n_calls)
        {
            throw std::runtime_error(config_.what);
        }
    }

    uint32_t call_count() const noexcept
    {
        return call_count_.load();
    }
    void reset_call_count() noexcept
    {
        call_count_.store(0);
    }
    const Config& config() const noexcept
    {
        return config_;
    }

private:
    Config config_;
    std::atomic<uint32_t> call_count_{ 0 };
};

} // namespace viz::testing
