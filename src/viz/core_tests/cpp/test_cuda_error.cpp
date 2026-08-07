// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

// [unit] tests for the CUDA failure messages. The point of
// cuda_error.hpp is diagnosis, so what is asserted here is the CONTENT:
// a cross-device failure must name both devices and the fix, because
// CUDA itself reports that case as a bare "invalid argument".

#include <catch2/catch_test_macros.hpp>
#include <catch2/matchers/catch_matchers_string.hpp>
#include <viz/core/cuda_error.hpp>

#include <algorithm>
#include <cuda_runtime.h>
#include <stdexcept>

using Catch::Matchers::ContainsSubstring;
using viz::check_cuda;
using viz::cuda_error_message;

namespace
{

// The hint needs a live CUDA driver to read the current device, and it
// only fires when that device differs from viz's. Pick a device id that
// cannot be current so the mismatch branch is deterministic.
bool cuda_driver_present()
{
    int current = -1;
    return cudaGetDevice(&current) == cudaSuccess;
}

} // namespace

TEST_CASE("cuda_error_message states the failing call and CUDA's reason", "[unit][cuda_error]")
{
    const std::string msg = cuda_error_message(
        "QuadLayer", "cudaSignalExternalSemaphoresAsync(cuda_done_writing)", cudaErrorInvalidValue, /*viz_device=*/-1);
    CHECK_THAT(msg, ContainsSubstring("QuadLayer"));
    CHECK_THAT(msg, ContainsSubstring("cudaSignalExternalSemaphoresAsync(cuda_done_writing)"));
    CHECK_THAT(msg, ContainsSubstring(cudaGetErrorString(cudaErrorInvalidValue)));
    // viz_device < 0 means "unknown" — no diagnosis, no invented advice.
    CHECK_THAT(msg, !ContainsSubstring("cause:"));
}

TEST_CASE("cuda_error_message diagnoses a cross-device call", "[unit][cuda_error]")
{
    if (!cuda_driver_present())
    {
        SKIP("No CUDA driver — cudaGetDevice is what the hint reads");
    }
    int current = -1;
    REQUIRE(cudaGetDevice(&current) == cudaSuccess);

    // A device id that is not the current one: the situation a submit
    // from a foreign thread lands in.
    const int viz_device = current + 1;
    const std::string msg = cuda_error_message(
        "ProjectionLayer", "cudaSignalExternalSemaphoresAsync(cuda_done_writing)", cudaErrorInvalidValue, viz_device);

    CHECK_THAT(msg, ContainsSubstring("GPU " + std::to_string(current))); // where the caller is
    CHECK_THAT(msg, ContainsSubstring("GPU " + std::to_string(viz_device))); // where viz is
    CHECK_THAT(msg, ContainsSubstring("per-thread")); // why it is not a bad argument
    CHECK_THAT(msg, ContainsSubstring("cudaSetDevice(" + std::to_string(viz_device) + ")")); // the fix
    CHECK_THAT(msg, ContainsSubstring("cuda_device_id")); // where to get the id
    // Informative, not a wall of text: the diagnosis is two lines.
    CHECK(std::count(msg.begin(), msg.end(), '\n') == 2);
}

TEST_CASE("cuda_error_message stays quiet when the devices agree", "[unit][cuda_error]")
{
    if (!cuda_driver_present())
    {
        SKIP("No CUDA driver — cudaGetDevice is what the hint reads");
    }
    int current = -1;
    REQUIRE(cudaGetDevice(&current) == cudaSuccess);

    // Same device: the failure is something else entirely, and a device
    // lecture would send the reader down the wrong path.
    const std::string msg =
        cuda_error_message("QuadLayer", "cudaStreamSynchronize(submit)", cudaErrorInvalidValue, current);
    CHECK_THAT(msg, !ContainsSubstring("cause:"));
}

TEST_CASE("check_cuda throws only on failure", "[unit][cuda_error]")
{
    CHECK_NOTHROW(check_cuda(cudaSuccess, "QuadLayer", "cudaSetDevice", 0));
    CHECK_THROWS_AS(check_cuda(cudaErrorInvalidValue, "QuadLayer", "cudaSetDevice", 0), std::runtime_error);
}
