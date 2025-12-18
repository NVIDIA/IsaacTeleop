// SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#pragma once

#include "tracker.hpp"

#include <schema/head_generated.h>

#include <memory>

namespace core
{

// Head tracker - tracks HMD pose (returns HeadPoseT from FlatBuffer schema)
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
    const HeadPoseT& get_head() const;

protected:
    // Internal lifecycle methods - only accessible via friend classes
    friend class XrioSession;

    std::shared_ptr<ITrackerImpl> initialize(const OpenXRSessionHandles& handles) override;

private:
    // Implementation class declaration (Pimpl idiom)
    class Impl : public ITrackerImpl
    {
    public:
        // Constructor - throws std::runtime_error on failure
        explicit Impl(const OpenXRSessionHandles& handles);

        ~Impl();

        // Override from ITrackerImpl
        bool update(XrTime time) override;

        const HeadPoseT& get_head() const;

    private:
        const OpenXRCoreFunctions core_funcs_;
        XrSpace base_space_;
        XrSpacePtr view_space_;
        HeadPoseT head_;
        OpenXRCoreFunctions core_funcs_;
    };

    // Weak pointer to impl (owned by session)
    std::weak_ptr<Impl> cached_impl_;
};

} // namespace core
