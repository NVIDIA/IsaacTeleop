// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

// Perf audit tests:
//   A. GPU-timestamp infrastructure populates sane values when enabled.
//   B. Render hot path stays under a per-frame allocation ceiling.
// Run against kOffscreen for CI determinism; same code paths run on kXr.

#include <catch2/catch_test_macros.hpp>
#include <viz/layers/testing/clear_rect_layer.hpp>
#include <viz/session/viz_session.hpp>
#include <viz/test_support/test_helpers.hpp>

#include <atomic>
#include <cstdlib>
#include <new>

using viz::DisplayMode;
using viz::VizSession;
using viz::testing::ClearRectLayer;
using viz::testing::is_gpu_available;

// Global new/delete overrides for this test binary. Counter only
// increments while AllocCounter::Scope is alive so Catch2 / logging
// outside the measured window don't pollute the count.

namespace
{

std::atomic<int> g_alloc_count{ 0 };
std::atomic<bool> g_count_active{ false };

class AllocCounter
{
public:
    class Scope
    {
    public:
        Scope()
        {
            g_alloc_count.store(0, std::memory_order_relaxed);
            g_count_active.store(true, std::memory_order_release);
        }
        ~Scope()
        {
            g_count_active.store(false, std::memory_order_release);
        }
        Scope(const Scope&) = delete;
        Scope& operator=(const Scope&) = delete;
        int count() const noexcept
        {
            return g_alloc_count.load(std::memory_order_relaxed);
        }
    };
};

} // namespace

void* operator new(std::size_t n)
{
    void* p = std::malloc(n);
    if (p == nullptr)
    {
        throw std::bad_alloc{};
    }
    if (g_count_active.load(std::memory_order_acquire))
    {
        g_alloc_count.fetch_add(1, std::memory_order_relaxed);
    }
    return p;
}

void operator delete(void* p) noexcept
{
    std::free(p);
}

void operator delete(void* p, std::size_t /*sz*/) noexcept
{
    std::free(p);
}

void* operator new[](std::size_t n)
{
    void* p = std::malloc(n);
    if (p == nullptr)
    {
        throw std::bad_alloc{};
    }
    if (g_count_active.load(std::memory_order_acquire))
    {
        g_alloc_count.fetch_add(1, std::memory_order_relaxed);
    }
    return p;
}

void operator delete[](void* p) noexcept
{
    std::free(p);
}

void operator delete[](void* p, std::size_t /*sz*/) noexcept
{
    std::free(p);
}

// ─── Test A: GPU timestamp infrastructure ─────────────────────────────

TEST_CASE("VizCompositor populates GPU timestamps when gpu_timing is enabled", "[gpu][viz_session][perf]")
{
    if (!is_gpu_available())
    {
        SKIP("No Vulkan-capable GPU available");
    }

    constexpr uint32_t kSide = 256;

    VizSession::Config cfg{};
    cfg.mode = DisplayMode::kOffscreen;
    cfg.window_width = kSide;
    cfg.window_height = kSide;
    cfg.gpu_timing = true;

    auto session = VizSession::create(cfg);
    REQUIRE(session != nullptr);

    // ClearRectLayer issues real draw calls so the render-pass delta is non-trivial.
    session->add_layer<ClearRectLayer>(ClearRectLayer::Config{
        /*x=*/0,
        /*y=*/0,
        /*w=*/kSide,
        /*h=*/kSide,
        /*rgba=*/{ 1.0f, 0.5f, 0.0f, 1.0f },
        /*name=*/"timing_layer",
    });

    // Pre-render: all zero.
    {
        const auto& t = session->get_gpu_timing();
        CHECK(t.total_ms == 0.0f);
        CHECK(t.render_pass_ms == 0.0f);
        CHECK(t.post_pass_ms == 0.0f);
    }

    for (int i = 0; i < 5; ++i)
    {
        session->render();
    }

    const auto& t = session->get_gpu_timing();
    INFO("total=" << t.total_ms << "ms render_pass=" << t.render_pass_ms << "ms post_pass=" << t.post_pass_ms << "ms");

    // timestampPeriod==0 → device doesn't support timestamps. Accept.
    if (t.total_ms == 0.0f)
    {
        SUCCEED("Device does not support timestamp queries; deltas remain zero");
        return;
    }

    CHECK(t.total_ms > 0.0f);
    CHECK(t.render_pass_ms > 0.0f);
    CHECK(t.post_pass_ms >= 0.0f);
    CHECK(t.render_pass_ms + t.post_pass_ms <= t.total_ms + 0.01f);
    CHECK(t.total_ms < 1000.0f); // anything above 1s is a bug, not a slow GPU
}

TEST_CASE("VizCompositor leaves GPU timing zeroed when gpu_timing is disabled", "[gpu][viz_session][perf]")
{
    if (!is_gpu_available())
    {
        SKIP("No Vulkan-capable GPU available");
    }

    VizSession::Config cfg{};
    cfg.mode = DisplayMode::kOffscreen;
    cfg.window_width = 64;
    cfg.window_height = 64;
    // gpu_timing left at default (false).

    auto session = VizSession::create(cfg);
    REQUIRE(session != nullptr);
    session->render();

    const auto& t = session->get_gpu_timing();
    CHECK(t.total_ms == 0.0f);
    CHECK(t.render_pass_ms == 0.0f);
    CHECK(t.post_pass_ms == 0.0f);
}

// ─── Test B: Per-frame allocation audit ──────────────────────────────

TEST_CASE("Render hot path stays under per-frame allocation ceiling", "[gpu][viz_session][perf]")
{
    if (!is_gpu_available())
    {
        SKIP("No Vulkan-capable GPU available");
    }

    constexpr uint32_t kSide = 256;

    VizSession::Config cfg{};
    cfg.mode = DisplayMode::kOffscreen;
    cfg.window_width = kSide;
    cfg.window_height = kSide;

    auto session = VizSession::create(cfg);
    REQUIRE(session != nullptr);
    session->add_layer<ClearRectLayer>(ClearRectLayer::Config{
        /*x=*/0,
        /*y=*/0,
        /*w=*/kSide,
        /*h=*/kSide,
        /*rgba=*/{ 0.2f, 0.4f, 0.6f, 1.0f },
        /*name=*/"audit_layer",
    });

    // Warmup so first-frame lazy init isn't charged against steady state.
    for (int i = 0; i < 3; ++i)
    {
        session->render();
    }

    constexpr int kFrames = 10;
    int allocs = 0;
    {
        AllocCounter::Scope scope;
        for (int i = 0; i < kFrames; ++i)
        {
            session->render();
        }
        allocs = scope.count();
    }
    INFO("allocations during " << kFrames << " steady-state render() calls: " << allocs);

    // Generous ceiling — flags order-of-magnitude regressions, not
    // single-allocation drift. If this fails routinely, profile the
    // diff before bumping.
    constexpr int kMaxAllocsPerFrameCeiling = 64;
    CHECK(allocs <= kFrames * kMaxAllocsPerFrameCeiling);
}
