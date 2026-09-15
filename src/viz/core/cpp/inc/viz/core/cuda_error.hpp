// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#pragma once

#include <cuda_runtime.h>
#include <stdexcept>
#include <string>

namespace viz
{

// Failed-CUDA-call reporting for the interop paths.
//
// CUDA's own strings are useless on their own here: the whole
// CUDA-Vulkan interop surface reports a cross-device call as a bare
// "invalid argument", which reads like a bad parameter and sends people
// looking at buffer shapes and stream handles. It is almost always the
// same thing instead — the calling THREAD is on a different GPU than the
// one viz's images and semaphores live on, because cudaSetDevice() is
// per-thread state and viz's device is not necessarily device 0 (Vulkan
// and CUDA enumerate GPUs in different orders, so auto-pick routinely
// lands on a non-zero CUDA index on multi-GPU machines).
//
// So: name the two devices and the fix, in one line. Anything longer
// gets skimmed past — the ids and the call to make are the payload.
namespace detail
{

inline std::string cuda_device_mismatch_hint(int viz_device)
{
    int current = -1;
    if (cudaGetDevice(&current) != cudaSuccess || current == viz_device || viz_device < 0)
    {
        return {};
    }
    const std::string viz_id = std::to_string(viz_device);
    return "\n  cause: this thread is on GPU " + std::to_string(current) + ", viz is on GPU " + viz_id +
           " (interop is same-device; cudaSetDevice is per-thread)."
           "\n  fix: cudaSetDevice(" +
           viz_id + ") on this thread — id = VizSession.cuda_device_id.";
}

} // namespace detail

// Message for a failed CUDA call. ``subsystem`` is the reporting type
// ("QuadLayer"), ``call`` the CUDA entry point plus any disambiguating
// detail ("cudaSignalExternalSemaphoresAsync(cuda_done_writing)").
// ``viz_device`` is the device the interop objects belong to (pass -1
// when it is not known — the hint is then omitted).
inline std::string cuda_error_message(const std::string& subsystem, const std::string& call, cudaError_t err, int viz_device)
{
    return subsystem + ": " + call + " failed: " + cudaGetErrorString(err) +
           detail::cuda_device_mismatch_hint(viz_device);
}

// Throw std::runtime_error(cuda_error_message(...)) unless the call succeeded.
inline void check_cuda(cudaError_t err, const std::string& subsystem, const std::string& call, int viz_device)
{
    if (err != cudaSuccess)
    {
        throw std::runtime_error(cuda_error_message(subsystem, call, err, viz_device));
    }
}

} // namespace viz
