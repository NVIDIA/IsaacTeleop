// SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#include "clock_sync/xr_clock_translator.hpp"

#include <oxr/oxr_session.hpp>
#include <oxr_utils/oxr_time.hpp>

#include <iostream>

namespace core
{

// ============================================================================
// XrClockTranslator::Impl
// ============================================================================

struct XrClockTranslator::Impl
{
    std::unique_ptr<OpenXRSession> session;
    std::unique_ptr<XrTimeConverter> time_converter;
};

// ============================================================================
// Construction
// ============================================================================

XrClockTranslator::XrClockTranslator() : impl_(std::make_unique<Impl>())
{
}

XrClockTranslator::~XrClockTranslator() = default;

std::shared_ptr<XrClockTranslator> XrClockTranslator::Create(const std::string& app_name,
                                                             const std::vector<std::string>& extra_extensions)
{
    auto translator = std::shared_ptr<XrClockTranslator>(new XrClockTranslator());

    // Combine time conversion extensions with any extra extensions
    auto extensions = XrTimeConverter::get_required_extensions();
    extensions.insert(extensions.end(), extra_extensions.begin(), extra_extensions.end());

    translator->impl_->session = std::make_unique<OpenXRSession>(app_name, extensions);
    translator->impl_->time_converter =
        std::make_unique<XrTimeConverter>(translator->impl_->session->get_handles());

    std::cout << "[XrClockTranslator] Initialised (translating CLOCK_MONOTONIC -> XrTime)" << std::endl;
    return translator;
}

// ============================================================================
// Translation
// ============================================================================

clock_ns_t XrClockTranslator::translate(clock_ns_t monotonic_ns) const
{
    XrTime xr_time = impl_->time_converter->convert_monotonic_ns_to_xrtime(monotonic_ns);
    return static_cast<clock_ns_t>(xr_time);
}

ClockTranslator XrClockTranslator::make_translator()
{
    auto self = shared_from_this();
    return [self](clock_ns_t monotonic_ns) -> clock_ns_t { return self->translate(monotonic_ns); };
}

} // namespace core
