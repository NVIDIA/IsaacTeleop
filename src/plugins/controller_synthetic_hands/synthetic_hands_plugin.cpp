#include <controller_synthetic_hands/synthetic_hands_plugin.hpp>

#include <algorithm>
#include <chrono>
#include <iostream>

namespace plugins
{
namespace controller_synthetic_hands
{

// Toggle between space-based and pose-based hand injection
// true = use controller spaces directly (primary method)
// false = read controller poses and generate in world space (secondary method)
constexpr bool USE_SPACE_BASED_INJECTION = false;

SyntheticHandsPlugin::SyntheticHandsPlugin(const std::string& plugin_root_id) noexcept(false)
    : m_root_id(plugin_root_id)
{
    std::cout << "Initializing SyntheticHandsPlugin with root: " << m_root_id << std::endl;

    // Initialize session
    plugin_utils::SessionConfig config;
    config.app_name = "ControllerSyntheticHands";
    config.extensions = { XR_NVX1_DEVICE_INTERFACE_BASE_EXTENSION_NAME, XR_MND_HEADLESS_EXTENSION_NAME,
                          XR_EXTX_OVERLAY_EXTENSION_NAME };
    config.use_overlay_mode = true; // Required for headless mode

    // Session constructor will throw if it fails
    m_session.emplace(config);
    const auto& handles = m_session->handles();

    m_session->begin();

    // Initialize controllers
    m_controllers.emplace(handles.instance, handles.session, handles.reference_space);

    // Initialize hand injection using the selected method
    if (USE_SPACE_BASED_INJECTION)
    {
        m_injector.emplace(
            handles.instance, handles.session, m_controllers->left_aim_space(), m_controllers->right_aim_space());
    }
    else
    {
        m_injector.emplace(handles.instance, handles.session, handles.reference_space);
    }

    // Start worker thread
    m_running = true;
    m_thread = std::thread(&SyntheticHandsPlugin::worker_thread, this);

    std::cout << "SyntheticHandsPlugin initialized and running" << std::endl;
}

SyntheticHandsPlugin::~SyntheticHandsPlugin()
{
    std::cout << "Shutting down SyntheticHandsPlugin..." << std::endl;

    m_running = false;
    m_thread.join();
}

XrTime SyntheticHandsPlugin::get_current_time()
{
    auto now = std::chrono::steady_clock::now();
    auto ns = std::chrono::duration_cast<std::chrono::nanoseconds>(now.time_since_epoch());
    return static_cast<XrTime>(ns.count());
}

void SyntheticHandsPlugin::worker_thread()
{
    XrHandJointLocationEXT left_joints[XR_HAND_JOINT_COUNT_EXT];
    XrHandJointLocationEXT right_joints[XR_HAND_JOINT_COUNT_EXT];

    // Smooth curl transition state
    float left_curl_current = 0.0f;
    float right_curl_current = 0.0f;
    constexpr float CURL_SPEED = 5.0f;
    constexpr float FRAME_TIME = 0.016f;

    while (m_running)
    {
        XrTime time = get_current_time();

        try
        {
            m_controllers->update(time);
        }
        catch (const std::exception& e)
        {
            std::cerr << "Controller update failed: " << e.what() << std::endl;
            std::this_thread::sleep_for(std::chrono::milliseconds(16));
            continue;
        }

        // Get controller states
        const auto& left = m_controllers->left();
        const auto& right = m_controllers->right();

        // Get target curl values
        float left_target = left.trigger_value;
        float right_target = right.trigger_value;

        // Smoothly interpolate
        float curl_delta = CURL_SPEED * FRAME_TIME;

        if (left_curl_current < left_target)
            left_curl_current = std::min(left_curl_current + curl_delta, left_target);
        else if (left_curl_current > left_target)
            left_curl_current = std::max(left_curl_current - curl_delta, left_target);

        if (right_curl_current < right_target)
            right_curl_current = std::min(right_curl_current + curl_delta, right_target);
        else if (right_curl_current > right_target)
            right_curl_current = std::max(right_curl_current - curl_delta, right_target);

        // Update exposed state
        {
            std::lock_guard<std::mutex> lock(m_state_mutex);
            m_left_curl = left_curl_current;
            m_right_curl = right_curl_current;
        }

        if (m_left_enabled)
        {
            if (USE_SPACE_BASED_INJECTION)
            {
                m_hand_gen.generate_relative(left_joints, true, left_curl_current);
                m_injector->push_left(left_joints, time);
            }
            else if (left.grip_valid && left.aim_valid)
            {
                XrPosef wrist;
                wrist.position = left.aim_pose.position;
                wrist.orientation = left.aim_pose.orientation;
                m_hand_gen.generate(left_joints, wrist, true, left_curl_current);
                m_injector->push_left(left_joints, time);
            }
        }

        if (m_right_enabled)
        {
            if (USE_SPACE_BASED_INJECTION)
            {
                m_hand_gen.generate_relative(right_joints, false, right_curl_current);
                m_injector->push_right(right_joints, time);
            }
            else if (right.grip_valid && right.aim_valid)
            {
                XrPosef wrist;
                wrist.position = right.aim_pose.position;
                wrist.orientation = right.aim_pose.orientation;
                m_hand_gen.generate(right_joints, wrist, false, right_curl_current);
                m_injector->push_right(right_joints, time);
            }
        }

        std::this_thread::sleep_for(std::chrono::milliseconds(16));
    }
}

} // namespace controller_synthetic_hands
} // namespace plugins
