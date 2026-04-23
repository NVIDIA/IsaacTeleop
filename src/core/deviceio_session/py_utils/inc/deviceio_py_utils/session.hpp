// SPDX-FileCopyrightText: Copyright (c) 2025-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#pragma once

#include <deviceio_session/deviceio_session.hpp>
#include <deviceio_session/replay_session.hpp>
#include <pybind11/pybind11.h>

#include <memory>
#include <stdexcept>
#include <vector>

namespace py = pybind11;

namespace core
{

// Python-facing config wrapper: holds the C++ McapRecordingConfig (raw pointers)
// alongside shared_ptr ownership so trackers stay alive while the config exists.
struct PyMcapRecordingConfig
{
    McapRecordingConfig config;
    std::vector<std::shared_ptr<ITracker>> tracker_refs;
};

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
    PyDeviceIOSession(std::unique_ptr<DeviceIOSession> impl, std::vector<std::shared_ptr<ITracker>> tracker_refs)
        : impl_(std::move(impl)), tracker_refs_(std::move(tracker_refs))
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
        tracker_refs_.clear();
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
    std::vector<std::shared_ptr<ITracker>> tracker_refs_;
};

// Python-facing config wrapper: holds the C++ McapReplayConfig (raw pointers)
// alongside shared_ptr ownership so trackers stay alive while the config exists.
struct PyMcapReplayConfig
{
    McapReplayConfig config;
    std::vector<std::shared_ptr<ITracker>> tracker_refs;
};

/**
 * @brief Python-facing wrapper for ReplaySession with the same context-manager
 *        and lifetime semantics as PyDeviceIOSession.
 */
class PyReplaySession : public ITrackerSession
{
public:
    PyReplaySession(std::unique_ptr<ReplaySession> impl, std::vector<std::shared_ptr<ITracker>> tracker_refs)
        : impl_(std::move(impl)), tracker_refs_(std::move(tracker_refs))
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
        tracker_refs_.clear();
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
    std::vector<std::shared_ptr<ITracker>> tracker_refs_;
};

} // namespace core
