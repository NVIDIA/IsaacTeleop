// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

// Unit tests for ThrowingLayer's bookkeeping (call_count + reset).
// record() exception behavior is exercised by integration tests in
// viz/session_tests/ where a real RenderTarget is available.

#include <catch2/catch_test_macros.hpp>
#include <viz/layers/testing/throwing_layer.hpp>

using viz::testing::ThrowingLayer;

TEST_CASE("ThrowingLayer initial state", "[unit][throwing_layer]")
{
    ThrowingLayer layer(ThrowingLayer::Config{ 5 });
    CHECK(layer.call_count() == 0);
    CHECK(layer.is_visible());
    CHECK(layer.config().throw_after_n_calls == 5);
}

TEST_CASE("ThrowingLayer reset_call_count zeroes the counter", "[unit][throwing_layer]")
{
    ThrowingLayer layer(ThrowingLayer::Config{});
    // We can't drive record() here without a real RenderTarget; just
    // verify the reset method is wired.
    layer.reset_call_count();
    CHECK(layer.call_count() == 0);
}
