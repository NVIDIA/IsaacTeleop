#pragma once
#include <controller_synthetic_hands/hand_generator.hpp>
#include <deviceio/controller_tracker.hpp>
#include <deviceio/deviceio_session.hpp>
#include <oxr/oxr_session.hpp>
#include <plugin_utils/hand_injector.hpp>

#include <atomic>
#include <memory>
#include <mutex>
#include <optional>
#include <string>
#include <thread>

namespace plugins
{
namespace controller_synthetic_hands
{

class SyntheticHandsPlugin
{
public:
    explicit SyntheticHandsPlugin(const std::string& plugin_root_id) noexcept(false);
    ~SyntheticHandsPlugin();

    SyntheticHandsPlugin(const SyntheticHandsPlugin&) = delete;
    SyntheticHandsPlugin& operator=(const SyntheticHandsPlugin&) = delete;
    SyntheticHandsPlugin(SyntheticHandsPlugin&&) = delete;
    SyntheticHandsPlugin& operator=(SyntheticHandsPlugin&&) = delete;

private:
    void worker_thread();

    std::shared_ptr<core::OpenXRSession> m_session;
    std::shared_ptr<core::ControllerTracker> m_controller_tracker;
    std::unique_ptr<core::DeviceIOSession> m_deviceio_session;
    std::optional<plugin_utils::HandInjector> m_injector;
    HandGenerator m_hand_gen;

    std::thread m_thread;
    std::atomic<bool> m_running{ false };
    std::atomic<bool> m_left_enabled{ true };
    std::atomic<bool> m_right_enabled{ true };

    std::string m_root_id;

    // Current state
    std::mutex m_state_mutex;
    float m_left_curl = 0.0f;
    float m_right_curl = 0.0f;
};

} // namespace controller_synthetic_hands
} // namespace plugins
