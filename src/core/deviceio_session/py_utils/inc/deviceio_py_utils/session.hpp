// SPDX-FileCopyrightText: Copyright (c) 2025-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#pragma once

#include <deviceio_session/deviceio_session.hpp>
#include <deviceio_session/replay_session.hpp>
#include <pybind11/pybind11.h>

#include <memory>
#include <stdexcept>

namespace py = pybind11;

namespace core
{

/**
 * @brief Python-facing session wrapper: destroys the underlying DeviceIOSession in __exit__.
 *
 * Binding DeviceIOSession directly with a no-op __exit__ leaves destruction to the pybind
 * holder, which can run after the OpenXR session is torn down and produces invalid-handle
 * errors. This type inherits ITrackerSession and forwards get_tracker_impl() so tracker
 * accessors and MCAP record() accept the same Python object.
 */
class PyDeviceIOSession : public ITrackerSession
{
public:
    explicit PyDeviceIOSession(std::unique_ptr<DeviceIOSession> impl) : impl_(std::move(impl))
    {
    }

    void update()
    {
        if (!impl_)
        {
            throw std::runtime_error("Session has been closed/destroyed");
        }
        impl_->update();
    }

    void close()
    {
        impl_.reset();
    }

    PyDeviceIOSession& enter()
    {
        if (!impl_)
        {
            throw std::runtime_error("Session has been closed/destroyed");
        }
        return *this;
    }

    void exit(py::object, py::object, py::object)
    {
        close();
    }

    DeviceIOSession& native()
    {
        if (!impl_)
        {
            throw std::runtime_error("Session has been closed/destroyed");
        }
        return *impl_;
    }

    const ITrackerImpl& get_tracker_impl(const ITracker& tracker) const override
    {
        if (!impl_)
        {
            throw std::runtime_error("Session has been closed/destroyed");
        }
        return impl_->get_tracker_impl(tracker);
    }

private:
    std::unique_ptr<DeviceIOSession> impl_;
};

/**
 * @brief Python-facing wrapper for ReplaySession with the same context-manager
 *        and lifetime semantics as PyDeviceIOSession.
 */
class PyReplaySession : public ITrackerSession
{
public:
    explicit PyReplaySession(std::unique_ptr<ReplaySession> impl) : impl_(std::move(impl))
    {
    }

    void update()
    {
        if (!impl_)
        {
            throw std::runtime_error("ReplaySession has been closed/destroyed");
        }
        impl_->update();
    }

    void close()
    {
        impl_.reset();
    }

    PyReplaySession& enter()
    {
        if (!impl_)
        {
            throw std::runtime_error("ReplaySession has been closed/destroyed");
        }
        return *this;
    }

    void exit(py::object, py::object, py::object)
    {
        close();
    }

    const ITrackerImpl& get_tracker_impl(const ITracker& tracker) const override
    {
        if (!impl_)
        {
            throw std::runtime_error("ReplaySession has been closed/destroyed");
        }
        return impl_->get_tracker_impl(tracker);
    }

private:
    std::unique_ptr<ReplaySession> impl_;
};

} // namespace core
