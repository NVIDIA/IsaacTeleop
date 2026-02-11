// SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#pragma once

#include "oxr_bundle.hpp"

#include <string>
#include <vector>

class OpenXRCreator
{
public:
    OpenXRCreator();
    ~OpenXRCreator();

    /** Headless init: creates instance (with headless + optional extensions) and session. */
    bool initializeHeadless(const std::vector<std::string>& optional_extensions = {});

    /*!
     * Get OpenXR bundle for use in other classes.
     *
     * The bundle is owned by the OpenXRCreator class and only lives for the
     * lifetime of the OpenXRCreator class. It is as thread safe as the
     * OpenXR handles themselves. The function initializeHeadless() must be called
     * before calling this method.
     *
     * @return A reference to the OpenXR bundle.
     */
    const OpenXRBundle& getBundle() const;


private:
    class Bundle : public OpenXRBundle
    {
    public:
        virtual ~Bundle() = default;
    };


private:
    bool createInstance(const std::vector<std::string>& requested_extensions);
    bool getSystem();
    bool createSession();

    Bundle bundle_{};
    XrFormFactor form_factor_;
};
