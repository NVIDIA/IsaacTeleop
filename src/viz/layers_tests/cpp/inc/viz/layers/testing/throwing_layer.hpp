// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#pragma once

#include <viz/core/render_target.hpp>
#include <viz/core/viz_types.hpp>
#include <viz/session/layer_base.hpp>
#include <vulkan/vulkan.h>

#include <atomic>
#include <cstdint>
#include <stdexcept>
#include <string>
#include <vector>

namespace viz::testing
{

// Test layer that throws from record() to verify compositor/session
// recovery (no fence deadlock, no leaked state).
//   throw_after_n_calls = 0  → throw on every call.
//   throw_after_n_calls = N  → N successful calls, then throw forever
//                              (reset_call_count() clears).
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
