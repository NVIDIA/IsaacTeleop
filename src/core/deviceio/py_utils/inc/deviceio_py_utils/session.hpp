// SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#pragma once

#include <deviceio/deviceio_session.hpp>
#include <pybind11/pybind11.h>

#include <memory>
#include <stdexcept>

namespace py = pybind11;

// Wrapper class to enforce RAII in Python by holding the unique_ptr exclusively.
// Other C++ modules (like mcap) should include this header and accept PyDeviceIOSession&
// directly, calling native() internally. This prevents dangling pointers when the
// session is destroyed after exiting the Python with: block.
class PyDeviceIOSession
{
public:
    PyDeviceIOSession(std::unique_ptr<core::DeviceIOSession> impl) : impl_(std::move(impl))
    {
    }

    bool update()
    {
        if (!impl_)
        {
            throw std::runtime_error("Session has been closed/destroyed");
        }
        return impl_->update();
    }

    void close()
    {
        impl_.reset(); // Destroys the underlying C++ object!
    }

    /** Discard XR handle ownership for all trackers (call when runtime was invalidated externally, e.g. Stop XR). */
    void discard_oxr_resources()
    {
        if (impl_)
        {
            impl_->discard_oxr_resources();
        }
    }

    PyDeviceIOSession& enter()
    {
        return *this;
    }

    // Reset unique_ptr on exit to enforce destruction
    void exit(py::object, py::object, py::object)
    {
        close();
    }

    core::DeviceIOSession& native()
    {
        if (!impl_)
        {
            throw std::runtime_error("Session has been closed/destroyed");
        }
        return *impl_;
    }

private:
    std::unique_ptr<core::DeviceIOSession> impl_;
};
