// SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#pragma once

#include "tracker.hpp"

#include <memory>

namespace oxr
{

// Head pose data
struct HeadPose
{
    float position[3]; // x, y, z in meters
    float orientation[4]; // x, y, z, w (quaternion)
    bool is_valid;
    XrTime timestamp;
};

// Head tracker - tracks HMD pose
// PUBLIC API: Only exposes query methods
class HeadTracker : public ITracker
{
public:
    HeadTracker();
    ~HeadTracker() override;

    // Public API - what external users see
    std::vector<std::string> get_required_extensions() const override;
    std::string get_name() const override
    {
        return "HeadTracker";
    }
    bool is_initialized() const override;

    // Query methods - public API for getting head data
    const HeadPose& get_head() const;

protected:
    // Internal lifecycle methods - only accessible via friend classes
    friend class TeleopSession;

    std::shared_ptr<ITrackerImpl> initialize(const OpenXRSessionHandles& handles) override;

private:
    // Implementation class declaration (Pimpl idiom)
    class Impl : public ITrackerImpl
    {
    public:
        // Factory function for creating the Impl - returns nullptr on failure
        static std::unique_ptr<Impl> create(const OpenXRSessionHandles& handles);

        ~Impl();

        // Override from ITrackerImpl
        bool update(XrTime time) override;

        const HeadPose& get_head() const;

    private:
        // Private constructor - only callable from factory function
        Impl(XrSpace base_space, XrSpace view_space, const OpenXRCoreFunctions& core_funcs);

        void cleanup();

        XrSpace base_space_;
        XrSpace view_space_;
        HeadPose head_;
        OpenXRCoreFunctions core_funcs_;
    };

    // Weak pointer to impl (owned by session)
    std::weak_ptr<Impl> cached_impl_;
};

} // namespace oxr
