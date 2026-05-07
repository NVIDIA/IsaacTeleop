// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

// M5 closure tests A + B from the perf-audit list:
//
//   A. GPU-timestamp infrastructure — proves the compositor's opt-in
//      timestamp queries populate sane values. Doesn't assert wall-clock
//      bounds (CI hardware varies); checks structural invariants
//      (fields populated, total >= sum-of-parts, monotonically positive).
//
//   B. Per-frame allocation audit — guards against regressions where a
//      heap allocation lands on the render hot path. Tracks new/delete
//      via a global counter, asserts steady-state allocations stay
//      under a small ceiling.
//
// Both run against the offscreen backend (kOffscreen) so they're CI-
// friendly; the same compositor + post-pass code runs under kXr, so
// the regressions these catch apply to the XR path too.

#include "test_helpers.hpp"

#include <catch2/catch_test_macros.hpp>
#include <viz/layers/testing/clear_rect_layer.hpp>
#include <viz/session/viz_session.hpp>

#include <atomic>
#include <cstdlib>
#include <new>

using viz::DisplayMode;
using viz::VizSession;
using viz::testing::ClearRectLayer;
using viz::testing::is_gpu_available;

// ─── Allocation counter (Test B) ───────────────────────────────────────
//
// Global new/delete overrides for THIS test binary. The counter only
// increments while AllocCounter::Scope is alive — Catch2 / fmt / spdlog
// allocate freely outside the scope without polluting the count.
//
// Correctness: malloc/free pair-balance is unaffected; we just route
// through the standard allocator. Multiple-binary setups would need
// per-binary symbol resolution, but Catch2 builds one executable, so
// these overrides apply only to viz_session_tests.

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

    // Need at least one drawing layer so the render-pass timestamp
    // delta is non-trivial. ClearRectLayer issues vkCmdDraw calls.
    session->add_layer<ClearRectLayer>(ClearRectLayer::Config{
        /*x=*/0,
        /*y=*/0,
        /*w=*/kSide,
        /*h=*/kSide,
        /*rgba=*/{ 1.0f, 0.5f, 0.0f, 1.0f },
        /*name=*/"timing_layer",
    });

    // Pre-flight: timing values are zero before any render() runs.
    {
        const auto& t = session->get_gpu_timing();
        CHECK(t.total_ms == 0.0f);
        CHECK(t.render_pass_ms == 0.0f);
        CHECK(t.post_pass_ms == 0.0f);
    }

    // Render a few frames to give the GPU a steady baseline.
    for (int i = 0; i < 5; ++i)
    {
        session->render();
    }

    const auto& t = session->get_gpu_timing();
    INFO("total=" << t.total_ms << "ms render_pass=" << t.render_pass_ms << "ms post_pass=" << t.post_pass_ms << "ms");

    // Some hardware reports timestampPeriod==0 (timestamps disabled);
    // in that case ALL fields stay zero — accept and move on.
    if (t.total_ms == 0.0f)
    {
        SUCCEED("Device does not support timestamp queries; deltas remain zero");
        return;
    }

    // Structural invariants — independent of hardware speed:
    // 1. Total time is positive.
    CHECK(t.total_ms > 0.0f);
    // 2. Render-pass time is positive (we did issue draw calls).
    CHECK(t.render_pass_ms > 0.0f);
    // 3. Post-pass time is non-negative (offscreen backend's post-pass
    //    is empty; kXr's would be the per-eye blit).
    CHECK(t.post_pass_ms >= 0.0f);
    // 4. Sum of parts can't exceed total wall time (within float slack).
    CHECK(t.render_pass_ms + t.post_pass_ms <= t.total_ms + 0.01f);
    // 5. Sanity ceiling — anything above 1 second is a bug, not a slow GPU.
    CHECK(t.total_ms < 1000.0f);
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

    // Warmup: lazy initialization (descriptor sets, command buffers,
    // first-frame fence priming) shouldn't be charged against steady-
    // state. 3 frames is enough for the offscreen backend to settle.
    for (int i = 0; i < 3; ++i)
    {
        session->render();
    }

    // Steady-state measurement window. Counts only allocations that
    // happen INSIDE the AllocCounter scope (Catch2 / logging traffic
    // outside doesn't count).
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

    // Ceiling is empirical — current code path allocates a handful of
    // small vectors per render() (visible_layers, wait/signal semaphores,
    // tile_layout aspects). The exact number is platform-sensitive
    // (allocator implementation, debug iterators, etc.); the bound here
    // is generous on purpose. The test exists to flag changes of an
    // ORDER OF MAGNITUDE — e.g. someone wires a per-frame std::string
    // construction or a vector that grows unboundedly.
    //
    // If this assertion starts failing routinely, profile the diff and
    // tighten the bound — don't just bump it.
    constexpr int kMaxAllocsPerFrameCeiling = 64;
    CHECK(allocs <= kFrames * kMaxAllocsPerFrameCeiling);
}
