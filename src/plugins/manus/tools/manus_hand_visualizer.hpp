// SPDX-FileCopyrightText: Copyright (c) 2025-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#pragma once

// Xlib must be included before Vulkan xlib surface header.
#include <X11/Xlib.h>
#include <X11/Xutil.h>
#include <core/manus_hand_tracking_plugin.hpp>
#include <vulkan/vulkan.h>
#include <vulkan/vulkan_xlib.h>

#include <array>
#include <cstring>
#include <iostream>
#include <limits>
#include <stdexcept>
#include <stop_token>
#include <string>
#include <unordered_map>
#include <vector>

namespace plugins
{
namespace manus
{

// ---------------------------------------------------------------------------
// Hand visualizer — opens an Xlib window and renders Manus hand skeletons
// using raw Vulkan (no external windowing library required).
//
// Usage (from a background thread):
//   HandVisualizer vis;      // throws if Vulkan/X11 unavailable
//   vis.run(tracker);        // blocks until window is closed
// ---------------------------------------------------------------------------
class HandVisualizer
{
public:
    // Construct and initialise Xlib + Vulkan.  Throws std::runtime_error if
    // either is unavailable so the caller can continue without the visualizer.
    HandVisualizer();
    ~HandVisualizer();

    // Block until the window is closed.  Reads hand data from tracker each frame.
    // Exits early when st.stop_requested() returns true, allowing the owning
    // std::jthread to request a clean shutdown before its destructor joins.
    void run(ManusTracker& tracker, std::stop_token st = {});

    // Non-copyable / non-movable (owns raw Vulkan handles).
    HandVisualizer(const HandVisualizer&) = delete;
    HandVisualizer& operator=(const HandVisualizer&) = delete;

private:
    // -----------------------------------------------------------------------
    // Pre-compiled SPIR-V for the vertex shader:
    //   layout(location=0) in  vec2 inPos;
    //   layout(location=1) in  vec3 inColor;
    //   layout(location=0) out vec3 fragColor;
    //   void main() { gl_Position = vec4(inPos, 0.0, 1.0); fragColor = inColor; }
    // -----------------------------------------------------------------------
    static constexpr uint32_t kVertSpv[] = {
        /* Header: magic, ver 1.0, gen 0, bound 30, schema 0 */
        0x07230203,
        0x00010000,
        0x00000000,
        0x0000001E,
        0x00000000,
        /* OpCapability Shader              */ 0x00020011,
        0x00000001,
        /* %1 OpExtInstImport "GLSL.std.450"*/ 0x0006000B,
        0x00000001,
        0x4C534C47,
        0x6474732E,
        0x3035342E,
        0x00000000,
        /* OpMemoryModel Logical GLSL450    */ 0x0003000E,
        0x00000000,
        0x00000001,
        /* OpEntryPoint Vertex %4 "main" %9 %12 %16 %23 */
        0x0009000F,
        0x00000000,
        0x00000004,
        0x6E69616D,
        0x00000000,
        0x00000009,
        0x0000000C,
        0x00000010,
        0x00000017,
        /* OpDecorate %9  Location 0        */ 0x00040047,
        0x00000009,
        0x0000001E,
        0x00000000,
        /* OpDecorate %12 Location 1        */ 0x00040047,
        0x0000000C,
        0x0000001E,
        0x00000001,
        /* OpDecorate %23 Location 0        */ 0x00040047,
        0x00000017,
        0x0000001E,
        0x00000000,
        /* OpMemberDecorate %14 0 BuiltIn Position */ 0x00050048,
        0x0000000E,
        0x00000000,
        0x0000000B,
        0x00000000,
        /* OpDecorate %14 Block             */ 0x00030047,
        0x0000000E,
        0x00000002,
        /* %2  OpTypeVoid                   */ 0x00020013,
        0x00000002,
        /* %3  OpTypeFunction %2            */ 0x00030021,
        0x00000003,
        0x00000002,
        /* %6  OpTypeFloat 32               */ 0x00030016,
        0x00000006,
        0x00000020,
        /* %7  OpTypeVector %6 2            */ 0x00040017,
        0x00000007,
        0x00000006,
        0x00000002,
        /* %8  OpTypePointer Input %7       */ 0x00040020,
        0x00000008,
        0x00000001,
        0x00000007,
        /* %9  OpVariable %8 Input          */ 0x0004003B,
        0x00000008,
        0x00000009,
        0x00000001,
        /* %10 OpTypeVector %6 3            */ 0x00040017,
        0x0000000A,
        0x00000006,
        0x00000003,
        /* %11 OpTypePointer Input %10      */ 0x00040020,
        0x0000000B,
        0x00000001,
        0x0000000A,
        /* %12 OpVariable %11 Input         */ 0x0004003B,
        0x0000000B,
        0x0000000C,
        0x00000001,
        /* %13 OpTypeVector %6 4            */ 0x00040017,
        0x0000000D,
        0x00000006,
        0x00000004,
        /* %14 OpTypeStruct %13 (gl_PerVertex: position only) */
        0x0003001E,
        0x0000000E,
        0x0000000D,
        /* %15 OpTypePointer Output %14     */ 0x00040020,
        0x0000000F,
        0x00000003,
        0x0000000E,
        /* %16 OpVariable %15 Output        */ 0x0004003B,
        0x0000000F,
        0x00000010,
        0x00000003,
        /* %17 OpTypeInt 32 signed          */ 0x00040015,
        0x00000011,
        0x00000020,
        0x00000001,
        /* %18 OpConstant int 0             */ 0x0004002B,
        0x00000011,
        0x00000012,
        0x00000000,
        /* %19 OpConstant float 0.0         */ 0x0004002B,
        0x00000006,
        0x00000013,
        0x00000000,
        /* %20 OpConstant float 1.0         */ 0x0004002B,
        0x00000006,
        0x00000014,
        0x3F800000,
        /* %21 OpTypePointer Output vec4    */ 0x00040020,
        0x00000015,
        0x00000003,
        0x0000000D,
        /* %22 OpTypePointer Output vec3    */ 0x00040020,
        0x00000016,
        0x00000003,
        0x0000000A,
        /* %23 OpVariable %22 Output        */ 0x0004003B,
        0x00000016,
        0x00000017,
        0x00000003,
        /* %4  OpFunction void None %3      */ 0x00050036,
        0x00000002,
        0x00000004,
        0x00000000,
        0x00000003,
        /* %5  OpLabel                      */ 0x000200F8,
        0x00000005,
        /* %24 OpLoad vec2 %9               */ 0x0004003D,
        0x00000007,
        0x00000018,
        0x00000009,
        /* %25 OpCompositeExtract float %24[0] */ 0x00050051,
        0x00000006,
        0x00000019,
        0x00000018,
        0x00000000,
        /* %26 OpCompositeExtract float %24[1] */ 0x00050051,
        0x00000006,
        0x0000001A,
        0x00000018,
        0x00000001,
        /* %27 OpCompositeConstruct vec4 (x,y,0,1) */
        0x00070050,
        0x0000000D,
        0x0000001B,
        0x00000019,
        0x0000001A,
        0x00000013,
        0x00000014,
        /* %28 OpAccessChain %21 %16[0]     */ 0x00050041,
        0x00000015,
        0x0000001C,
        0x00000010,
        0x00000012,
        /* OpStore gl_Position = %27        */ 0x0003003E,
        0x0000001C,
        0x0000001B,
        /* %29 OpLoad vec3 %12              */ 0x0004003D,
        0x0000000A,
        0x0000001D,
        0x0000000C,
        /* OpStore fragColor = %29          */ 0x0003003E,
        0x00000017,
        0x0000001D,
        /* OpReturn                         */ 0x000100FD,
        /* OpFunctionEnd                    */ 0x00010038,
    };

    // -----------------------------------------------------------------------
    // Pre-compiled SPIR-V for the fragment shader:
    //   layout(location=0) in  vec3 fragColor;
    //   layout(location=0) out vec4 outColor;
    //   void main() { outColor = vec4(fragColor, 1.0); }
    // -----------------------------------------------------------------------
    static constexpr uint32_t kFragSpv[] = {
        /* Header: magic, ver 1.0, gen 0, bound 19, schema 0 */
        0x07230203,
        0x00010000,
        0x00000000,
        0x00000013,
        0x00000000,
        /* OpCapability Shader              */ 0x00020011,
        0x00000001,
        /* %1 OpExtInstImport "GLSL.std.450"*/ 0x0006000B,
        0x00000001,
        0x4C534C47,
        0x6474732E,
        0x3035342E,
        0x00000000,
        /* OpMemoryModel Logical GLSL450    */ 0x0003000E,
        0x00000000,
        0x00000001,
        /* OpEntryPoint Fragment %4 "main" %9 %12 */
        0x0007000F,
        0x00000004,
        0x00000004,
        0x6E69616D,
        0x00000000,
        0x00000009,
        0x0000000C,
        /* OpExecutionMode OriginUpperLeft  */ 0x00030010,
        0x00000004,
        0x00000007,
        /* OpDecorate %9  Location 0        */ 0x00040047,
        0x00000009,
        0x0000001E,
        0x00000000,
        /* OpDecorate %12 Location 0        */ 0x00040047,
        0x0000000C,
        0x0000001E,
        0x00000000,
        /* %2  OpTypeVoid                   */ 0x00020013,
        0x00000002,
        /* %3  OpTypeFunction %2            */ 0x00030021,
        0x00000003,
        0x00000002,
        /* %6  OpTypeFloat 32               */ 0x00030016,
        0x00000006,
        0x00000020,
        /* %7  OpTypeVector %6 3            */ 0x00040017,
        0x00000007,
        0x00000006,
        0x00000003,
        /* %8  OpTypePointer Input %7       */ 0x00040020,
        0x00000008,
        0x00000001,
        0x00000007,
        /* %9  OpVariable %8 Input          */ 0x0004003B,
        0x00000008,
        0x00000009,
        0x00000001,
        /* %10 OpTypeVector %6 4            */ 0x00040017,
        0x0000000A,
        0x00000006,
        0x00000004,
        /* %11 OpTypePointer Output %10     */ 0x00040020,
        0x0000000B,
        0x00000003,
        0x0000000A,
        /* %12 OpVariable %11 Output        */ 0x0004003B,
        0x0000000B,
        0x0000000C,
        0x00000003,
        /* %13 OpConstant float 1.0         */ 0x0004002B,
        0x00000006,
        0x0000000D,
        0x3F800000,
        /* %4  OpFunction void None %3      */ 0x00050036,
        0x00000002,
        0x00000004,
        0x00000000,
        0x00000003,
        /* %5  OpLabel                      */ 0x000200F8,
        0x00000005,
        /* %14 OpLoad vec3 %9               */ 0x0004003D,
        0x00000007,
        0x0000000E,
        0x00000009,
        /* %15 OpCompositeExtract float %14[0] */ 0x00050051,
        0x00000006,
        0x0000000F,
        0x0000000E,
        0x00000000,
        /* %16 OpCompositeExtract float %14[1] */ 0x00050051,
        0x00000006,
        0x00000010,
        0x0000000E,
        0x00000001,
        /* %17 OpCompositeExtract float %14[2] */ 0x00050051,
        0x00000006,
        0x00000011,
        0x0000000E,
        0x00000002,
        /* %18 OpCompositeConstruct vec4    */ 0x00070050,
        0x0000000A,
        0x00000012,
        0x0000000F,
        0x00000010,
        0x00000011,
        0x0000000D,
        /* OpStore outColor = %18           */ 0x0003003E,
        0x0000000C,
        0x00000012,
        /* OpReturn                         */ 0x000100FD,
        /* OpFunctionEnd                    */ 0x00010038,
    };

    // -----------------------------------------------------------------------
    // Per-vertex data sent to the GPU.
    // -----------------------------------------------------------------------
    struct Vertex
    {
        float x, y; // NDC position
        float r, g, b; // linear colour
    };

    static constexpr uint32_t kWindowW = 800;
    static constexpr uint32_t kWindowH = 600;
    static constexpr uint32_t kMaxVertices = 16384;
    static constexpr float kCrossSize = 0.015f; // NDC half-length of joint marker

    // Left-hand colour: cyan-blue; right-hand colour: orange
    static constexpr std::array<float, 3> kLeftColor = { 0.20f, 0.65f, 1.00f };
    static constexpr std::array<float, 3> kRightColor = { 1.00f, 0.50f, 0.10f };

    // -----------------------------------------------------------------------
    // Projection modes
    // -----------------------------------------------------------------------
    enum class ProjectionMode
    {
        Top,
        Side
    };

    // -----------------------------------------------------------------------
    // Per-hand cached scale/3-D center (locked on first data frame, reset on disconnect)
    // -----------------------------------------------------------------------
    struct HandState
    {
        float scale = 0.0f;
        float cx = 0.0f, cy = 0.0f, cz = 0.0f;
    };
    HandState m_left_state, m_right_state;

    // -----------------------------------------------------------------------
    // Xlib state
    // -----------------------------------------------------------------------
    Display* m_dpy = nullptr;
    Window m_win = 0;
    Atom m_wm_del = 0;

    // -----------------------------------------------------------------------
    // Vulkan handles
    // -----------------------------------------------------------------------
    VkInstance m_instance = VK_NULL_HANDLE;
    VkSurfaceKHR m_surface = VK_NULL_HANDLE;
    VkPhysicalDevice m_pdev = VK_NULL_HANDLE;
    VkDevice m_dev = VK_NULL_HANDLE;
    VkQueue m_queue = VK_NULL_HANDLE;
    uint32_t m_qfam = 0;

    VkSwapchainKHR m_swapchain = VK_NULL_HANDLE;
    VkFormat m_sc_format = VK_FORMAT_UNDEFINED;
    VkExtent2D m_sc_extent = {};
    std::vector<VkImage> m_sc_images;
    std::vector<VkImageView> m_sc_views;

    VkRenderPass m_render_pass = VK_NULL_HANDLE;
    VkPipelineLayout m_pipe_layout = VK_NULL_HANDLE;
    VkPipeline m_pipeline = VK_NULL_HANDLE;

    std::vector<VkFramebuffer> m_framebuffers;
    VkCommandPool m_cmd_pool = VK_NULL_HANDLE;
    std::vector<VkCommandBuffer> m_cmd_bufs;

    VkSemaphore m_sem_image_avail = VK_NULL_HANDLE;
    VkSemaphore m_sem_render_done = VK_NULL_HANDLE;
    VkFence m_fence_in_flight = VK_NULL_HANDLE;

    VkBuffer m_vbuf = VK_NULL_HANDLE;
    VkDeviceMemory m_vbuf_mem = VK_NULL_HANDLE;
    void* m_vbuf_ptr = nullptr; // persistently mapped

    // -----------------------------------------------------------------------
    // Init helpers
    // -----------------------------------------------------------------------
    void initXlib();
    void initVulkan();
    void createSwapchain();
    void createRenderPass();
    void createPipeline();
    void createFramebuffers();
    void createCommandBuffers();
    void createSyncObjects();
    void createVertexBuffer();

    void destroySwapchainResources();

    // Releases all X11/Vulkan resources whose handles are non-null.
    // Safe to call on a partially-constructed object because every handle is
    // value-initialised to VK_NULL_HANDLE / nullptr / 0 and each branch is
    // guarded.  Called from both ~HandVisualizer() and the constructor's
    // catch block so that a mid-construction throw cannot leak handles.
    void teardown() noexcept;

    VkShaderModule createShaderModule(const uint32_t* spv, size_t bytes);

    // -----------------------------------------------------------------------
    // Per-frame helpers
    // -----------------------------------------------------------------------

    // Build geometry for one hand view panel.
    // mode     : Top (XZ plane, top-down) or Side (ZY plane, thumb-axis).
    // scale    : uniform scale shared between both views of this hand.
    // cx/cy/cz : 3-D world center of the hand (bbox midpoint).
    // ndc_cx/cy: NDC screen center of this quadrant.
    static void buildHandGeometry(const std::vector<SkeletonNode>& nodes,
                                  const std::vector<NodeInfo>& info,
                                  const std::array<float, 3>& colour,
                                  ProjectionMode mode,
                                  float scale,
                                  float cx,
                                  float cy,
                                  float cz,
                                  float ndc_cx,
                                  float ndc_cy,
                                  std::vector<Vertex>& verts);

    // Project one 3-D point: Top → (x, −z), Side → (−z, y).
    static std::pair<float, float> project(const ManusVec3& p, ProjectionMode mode);

    // Compute 3-D bounding box.  Returns false when nodes is empty.
    static bool computeBbox3D(const std::vector<SkeletonNode>& nodes,
                              float& xmin,
                              float& xmax,
                              float& ymin,
                              float& ymax,
                              float& zmin,
                              float& zmax);
};

// ===========================================================================
// Implementation (header-only)
// ===========================================================================

inline HandVisualizer::HandVisualizer()
{
    try
    {
        initXlib();
        initVulkan();
        createSwapchain();
        createRenderPass();
        createPipeline();
        createFramebuffers();
        createCommandBuffers();
        createSyncObjects();
        createVertexBuffer();
    }
    catch (...)
    {
        // The destructor is not invoked when a constructor throws, so we
        // must explicitly release whatever handles were created before the
        // failing call.
        teardown();
        throw;
    }
}

inline HandVisualizer::~HandVisualizer()
{
    teardown();
}

inline void HandVisualizer::teardown() noexcept
{
    if (m_dev)
        vkDeviceWaitIdle(m_dev);

    if (m_vbuf_ptr && m_vbuf_mem)
        vkUnmapMemory(m_dev, m_vbuf_mem);
    if (m_vbuf)
        vkDestroyBuffer(m_dev, m_vbuf, nullptr);
    if (m_vbuf_mem)
        vkFreeMemory(m_dev, m_vbuf_mem, nullptr);

    if (m_sem_image_avail)
        vkDestroySemaphore(m_dev, m_sem_image_avail, nullptr);
    if (m_sem_render_done)
        vkDestroySemaphore(m_dev, m_sem_render_done, nullptr);
    if (m_fence_in_flight)
        vkDestroyFence(m_dev, m_fence_in_flight, nullptr);

    destroySwapchainResources();

    if (m_render_pass)
        vkDestroyRenderPass(m_dev, m_render_pass, nullptr);
    if (m_pipe_layout)
        vkDestroyPipelineLayout(m_dev, m_pipe_layout, nullptr);
    if (m_pipeline)
        vkDestroyPipeline(m_dev, m_pipeline, nullptr);
    if (m_dev)
        vkDestroyDevice(m_dev, nullptr);
    if (m_surface)
        vkDestroySurfaceKHR(m_instance, m_surface, nullptr);
    if (m_instance)
        vkDestroyInstance(m_instance, nullptr);

    if (m_win && m_dpy)
        XDestroyWindow(m_dpy, m_win);
    if (m_dpy)
        XCloseDisplay(m_dpy);

    // Zero handles so repeated teardown() calls (e.g. via destructor after a
    // catch-rethrow) are harmless.
    m_vbuf_ptr = nullptr;
    m_vbuf = VK_NULL_HANDLE;
    m_vbuf_mem = VK_NULL_HANDLE;
    m_sem_image_avail = VK_NULL_HANDLE;
    m_sem_render_done = VK_NULL_HANDLE;
    m_fence_in_flight = VK_NULL_HANDLE;
    m_render_pass = VK_NULL_HANDLE;
    m_pipe_layout = VK_NULL_HANDLE;
    m_pipeline = VK_NULL_HANDLE;
    m_cmd_pool = VK_NULL_HANDLE;
    m_dev = VK_NULL_HANDLE;
    m_surface = VK_NULL_HANDLE;
    m_instance = VK_NULL_HANDLE;
    m_win = 0;
    m_dpy = nullptr;
}

// ---------------------------------------------------------------------------
inline void HandVisualizer::initXlib()
{
    m_dpy = XOpenDisplay(nullptr);
    if (!m_dpy)
        throw std::runtime_error("[Vis] Cannot open X11 display. Is DISPLAY set?");

    int screen = DefaultScreen(m_dpy);
    m_win = XCreateSimpleWindow(m_dpy, RootWindow(m_dpy, screen), 0, 0, kWindowW, kWindowH, 0,
                                BlackPixel(m_dpy, screen), BlackPixel(m_dpy, screen));

    XStoreName(m_dpy, m_win, "MANUS Data Visualizer");
    XSelectInput(m_dpy, m_win, StructureNotifyMask | KeyPressMask);
    XMapWindow(m_dpy, m_win);

    m_wm_del = XInternAtom(m_dpy, "WM_DELETE_WINDOW", False);
    XSetWMProtocols(m_dpy, m_win, &m_wm_del, 1);

    // Wait for the MapNotify event so the window is visible before we attach
    // a Vulkan surface.
    XEvent ev;
    while (true)
    {
        XNextEvent(m_dpy, &ev);
        if (ev.type == MapNotify)
            break;
    }
}

// ---------------------------------------------------------------------------
inline void HandVisualizer::initVulkan()
{
    // --- Instance -----------------------------------------------------------
    const char* inst_exts[] = { VK_KHR_SURFACE_EXTENSION_NAME, VK_KHR_XLIB_SURFACE_EXTENSION_NAME };
    const char* dev_exts[] = { VK_KHR_SWAPCHAIN_EXTENSION_NAME };

    VkApplicationInfo app_info{};
    app_info.sType = VK_STRUCTURE_TYPE_APPLICATION_INFO;
    app_info.pApplicationName = "ManusHandVisualizer";
    app_info.apiVersion = VK_API_VERSION_1_0;

    VkInstanceCreateInfo inst_ci{};
    inst_ci.sType = VK_STRUCTURE_TYPE_INSTANCE_CREATE_INFO;
    inst_ci.pApplicationInfo = &app_info;
    inst_ci.enabledExtensionCount = 2;
    inst_ci.ppEnabledExtensionNames = inst_exts;

    if (vkCreateInstance(&inst_ci, nullptr, &m_instance) != VK_SUCCESS)
        throw std::runtime_error("[Vis] vkCreateInstance failed");

    // --- Surface ------------------------------------------------------------
    VkXlibSurfaceCreateInfoKHR surf_ci{};
    surf_ci.sType = VK_STRUCTURE_TYPE_XLIB_SURFACE_CREATE_INFO_KHR;
    surf_ci.dpy = m_dpy;
    surf_ci.window = m_win;
    if (vkCreateXlibSurfaceKHR(m_instance, &surf_ci, nullptr, &m_surface) != VK_SUCCESS)
        throw std::runtime_error("[Vis] vkCreateXlibSurfaceKHR failed");

    // --- Physical device ----------------------------------------------------
    uint32_t pdev_count = 0;
    vkEnumeratePhysicalDevices(m_instance, &pdev_count, nullptr);
    if (pdev_count == 0)
        throw std::runtime_error("[Vis] No Vulkan physical devices found");

    std::vector<VkPhysicalDevice> pdevs(pdev_count);
    vkEnumeratePhysicalDevices(m_instance, &pdev_count, pdevs.data());

    for (auto& pd : pdevs)
    {
        uint32_t qfam_count = 0;
        vkGetPhysicalDeviceQueueFamilyProperties(pd, &qfam_count, nullptr);
        std::vector<VkQueueFamilyProperties> qfams(qfam_count);
        vkGetPhysicalDeviceQueueFamilyProperties(pd, &qfam_count, qfams.data());

        for (uint32_t i = 0; i < qfam_count; ++i)
        {
            if (!(qfams[i].queueFlags & VK_QUEUE_GRAPHICS_BIT))
                continue;

            VkBool32 can_present = VK_FALSE;
            vkGetPhysicalDeviceSurfaceSupportKHR(pd, i, m_surface, &can_present);
            if (!can_present)
                continue;

            m_pdev = pd;
            m_qfam = i;
            break;
        }
        if (m_pdev)
            break;
    }
    if (!m_pdev)
        throw std::runtime_error("[Vis] No suitable Vulkan device/queue found");

    // --- Logical device -----------------------------------------------------
    float queue_prio = 1.0f;
    VkDeviceQueueCreateInfo qci{};
    qci.sType = VK_STRUCTURE_TYPE_DEVICE_QUEUE_CREATE_INFO;
    qci.queueFamilyIndex = m_qfam;
    qci.queueCount = 1;
    qci.pQueuePriorities = &queue_prio;

    VkDeviceCreateInfo dev_ci{};
    dev_ci.sType = VK_STRUCTURE_TYPE_DEVICE_CREATE_INFO;
    dev_ci.queueCreateInfoCount = 1;
    dev_ci.pQueueCreateInfos = &qci;
    dev_ci.enabledExtensionCount = 1;
    dev_ci.ppEnabledExtensionNames = dev_exts;

    if (vkCreateDevice(m_pdev, &dev_ci, nullptr, &m_dev) != VK_SUCCESS)
        throw std::runtime_error("[Vis] vkCreateDevice failed");

    vkGetDeviceQueue(m_dev, m_qfam, 0, &m_queue);
}

// ---------------------------------------------------------------------------
inline void HandVisualizer::createSwapchain()
{
    // Query surface capabilities
    VkSurfaceCapabilitiesKHR caps{};
    vkGetPhysicalDeviceSurfaceCapabilitiesKHR(m_pdev, m_surface, &caps);

    // Choose extent
    m_sc_extent = (caps.currentExtent.width != UINT32_MAX) ? caps.currentExtent : VkExtent2D{ kWindowW, kWindowH };

    // Choose format: prefer B8G8R8A8_SRGB, fall back to first available
    uint32_t fmt_count = 0;
    vkGetPhysicalDeviceSurfaceFormatsKHR(m_pdev, m_surface, &fmt_count, nullptr);
    std::vector<VkSurfaceFormatKHR> fmts(fmt_count);
    vkGetPhysicalDeviceSurfaceFormatsKHR(m_pdev, m_surface, &fmt_count, fmts.data());

    m_sc_format = fmts[0].format;
    VkColorSpaceKHR color_space = fmts[0].colorSpace;
    for (auto& f : fmts)
    {
        if (f.format == VK_FORMAT_B8G8R8A8_SRGB && f.colorSpace == VK_COLOR_SPACE_SRGB_NONLINEAR_KHR)
        {
            m_sc_format = f.format;
            color_space = f.colorSpace;
            break;
        }
    }

    uint32_t img_count = caps.minImageCount + 1;
    if (caps.maxImageCount > 0 && img_count > caps.maxImageCount)
        img_count = caps.maxImageCount;

    VkSwapchainCreateInfoKHR sc_ci{};
    sc_ci.sType = VK_STRUCTURE_TYPE_SWAPCHAIN_CREATE_INFO_KHR;
    sc_ci.surface = m_surface;
    sc_ci.minImageCount = img_count;
    sc_ci.imageFormat = m_sc_format;
    sc_ci.imageColorSpace = color_space;
    sc_ci.imageExtent = m_sc_extent;
    sc_ci.imageArrayLayers = 1;
    sc_ci.imageUsage = VK_IMAGE_USAGE_COLOR_ATTACHMENT_BIT;
    sc_ci.imageSharingMode = VK_SHARING_MODE_EXCLUSIVE;
    sc_ci.preTransform = caps.currentTransform;
    sc_ci.compositeAlpha = VK_COMPOSITE_ALPHA_OPAQUE_BIT_KHR;
    sc_ci.presentMode = VK_PRESENT_MODE_FIFO_KHR;
    sc_ci.clipped = VK_TRUE;

    if (vkCreateSwapchainKHR(m_dev, &sc_ci, nullptr, &m_swapchain) != VK_SUCCESS)
        throw std::runtime_error("[Vis] vkCreateSwapchainKHR failed");

    uint32_t sc_img_count = 0;
    vkGetSwapchainImagesKHR(m_dev, m_swapchain, &sc_img_count, nullptr);
    m_sc_images.resize(sc_img_count);
    vkGetSwapchainImagesKHR(m_dev, m_swapchain, &sc_img_count, m_sc_images.data());

    m_sc_views.resize(sc_img_count);
    for (uint32_t i = 0; i < sc_img_count; ++i)
    {
        VkImageViewCreateInfo view_ci{};
        view_ci.sType = VK_STRUCTURE_TYPE_IMAGE_VIEW_CREATE_INFO;
        view_ci.image = m_sc_images[i];
        view_ci.viewType = VK_IMAGE_VIEW_TYPE_2D;
        view_ci.format = m_sc_format;
        view_ci.components.r = VK_COMPONENT_SWIZZLE_IDENTITY;
        view_ci.components.g = VK_COMPONENT_SWIZZLE_IDENTITY;
        view_ci.components.b = VK_COMPONENT_SWIZZLE_IDENTITY;
        view_ci.components.a = VK_COMPONENT_SWIZZLE_IDENTITY;
        view_ci.subresourceRange.aspectMask = VK_IMAGE_ASPECT_COLOR_BIT;
        view_ci.subresourceRange.baseMipLevel = 0;
        view_ci.subresourceRange.levelCount = 1;
        view_ci.subresourceRange.baseArrayLayer = 0;
        view_ci.subresourceRange.layerCount = 1;

        if (vkCreateImageView(m_dev, &view_ci, nullptr, &m_sc_views[i]) != VK_SUCCESS)
            throw std::runtime_error("[Vis] vkCreateImageView failed");
    }
}

// ---------------------------------------------------------------------------
inline void HandVisualizer::createRenderPass()
{
    VkAttachmentDescription color_att{};
    color_att.format = m_sc_format;
    color_att.samples = VK_SAMPLE_COUNT_1_BIT;
    color_att.loadOp = VK_ATTACHMENT_LOAD_OP_CLEAR;
    color_att.storeOp = VK_ATTACHMENT_STORE_OP_STORE;
    color_att.stencilLoadOp = VK_ATTACHMENT_LOAD_OP_DONT_CARE;
    color_att.stencilStoreOp = VK_ATTACHMENT_STORE_OP_DONT_CARE;
    color_att.initialLayout = VK_IMAGE_LAYOUT_UNDEFINED;
    color_att.finalLayout = VK_IMAGE_LAYOUT_PRESENT_SRC_KHR;

    VkAttachmentReference color_ref{};
    color_ref.attachment = 0;
    color_ref.layout = VK_IMAGE_LAYOUT_COLOR_ATTACHMENT_OPTIMAL;

    VkSubpassDescription subpass{};
    subpass.pipelineBindPoint = VK_PIPELINE_BIND_POINT_GRAPHICS;
    subpass.colorAttachmentCount = 1;
    subpass.pColorAttachments = &color_ref;

    VkSubpassDependency dep{};
    dep.srcSubpass = VK_SUBPASS_EXTERNAL;
    dep.dstSubpass = 0;
    dep.srcStageMask = VK_PIPELINE_STAGE_COLOR_ATTACHMENT_OUTPUT_BIT;
    dep.srcAccessMask = 0;
    dep.dstStageMask = VK_PIPELINE_STAGE_COLOR_ATTACHMENT_OUTPUT_BIT;
    dep.dstAccessMask = VK_ACCESS_COLOR_ATTACHMENT_WRITE_BIT;

    VkRenderPassCreateInfo rp_ci{};
    rp_ci.sType = VK_STRUCTURE_TYPE_RENDER_PASS_CREATE_INFO;
    rp_ci.attachmentCount = 1;
    rp_ci.pAttachments = &color_att;
    rp_ci.subpassCount = 1;
    rp_ci.pSubpasses = &subpass;
    rp_ci.dependencyCount = 1;
    rp_ci.pDependencies = &dep;

    if (vkCreateRenderPass(m_dev, &rp_ci, nullptr, &m_render_pass) != VK_SUCCESS)
        throw std::runtime_error("[Vis] vkCreateRenderPass failed");
}

// ---------------------------------------------------------------------------
inline VkShaderModule HandVisualizer::createShaderModule(const uint32_t* spv, size_t bytes)
{
    VkShaderModuleCreateInfo sm_ci{};
    sm_ci.sType = VK_STRUCTURE_TYPE_SHADER_MODULE_CREATE_INFO;
    sm_ci.codeSize = bytes;
    sm_ci.pCode = spv;

    VkShaderModule module = VK_NULL_HANDLE;
    if (vkCreateShaderModule(m_dev, &sm_ci, nullptr, &module) != VK_SUCCESS)
        throw std::runtime_error("[Vis] vkCreateShaderModule failed");
    return module;
}

// ---------------------------------------------------------------------------
inline void HandVisualizer::createPipeline()
{
    VkShaderModule vert = createShaderModule(kVertSpv, sizeof(kVertSpv));
    VkShaderModule frag = createShaderModule(kFragSpv, sizeof(kFragSpv));

    VkPipelineShaderStageCreateInfo stages[2]{};
    stages[0].sType = VK_STRUCTURE_TYPE_PIPELINE_SHADER_STAGE_CREATE_INFO;
    stages[0].stage = VK_SHADER_STAGE_VERTEX_BIT;
    stages[0].module = vert;
    stages[0].pName = "main";
    stages[1].sType = VK_STRUCTURE_TYPE_PIPELINE_SHADER_STAGE_CREATE_INFO;
    stages[1].stage = VK_SHADER_STAGE_FRAGMENT_BIT;
    stages[1].module = frag;
    stages[1].pName = "main";

    // Vertex input: binding 0, stride=sizeof(Vertex)=20
    VkVertexInputBindingDescription binding{};
    binding.binding = 0;
    binding.stride = sizeof(Vertex);
    binding.inputRate = VK_VERTEX_INPUT_RATE_VERTEX;

    VkVertexInputAttributeDescription attrs[2]{};
    // location 0: vec2 at offset 0
    attrs[0].binding = 0;
    attrs[0].location = 0;
    attrs[0].format = VK_FORMAT_R32G32_SFLOAT;
    attrs[0].offset = 0;
    // location 1: vec3 at offset 8
    attrs[1].binding = 0;
    attrs[1].location = 1;
    attrs[1].format = VK_FORMAT_R32G32B32_SFLOAT;
    attrs[1].offset = 8;

    VkPipelineVertexInputStateCreateInfo vert_input{};
    vert_input.sType = VK_STRUCTURE_TYPE_PIPELINE_VERTEX_INPUT_STATE_CREATE_INFO;
    vert_input.vertexBindingDescriptionCount = 1;
    vert_input.pVertexBindingDescriptions = &binding;
    vert_input.vertexAttributeDescriptionCount = 2;
    vert_input.pVertexAttributeDescriptions = attrs;

    VkPipelineInputAssemblyStateCreateInfo ia{};
    ia.sType = VK_STRUCTURE_TYPE_PIPELINE_INPUT_ASSEMBLY_STATE_CREATE_INFO;
    ia.topology = VK_PRIMITIVE_TOPOLOGY_LINE_LIST;
    ia.primitiveRestartEnable = VK_FALSE;

    // Dynamic viewport and scissor
    VkDynamicState dyn_states[] = { VK_DYNAMIC_STATE_VIEWPORT, VK_DYNAMIC_STATE_SCISSOR };
    VkPipelineDynamicStateCreateInfo dyn_state{};
    dyn_state.sType = VK_STRUCTURE_TYPE_PIPELINE_DYNAMIC_STATE_CREATE_INFO;
    dyn_state.dynamicStateCount = 2;
    dyn_state.pDynamicStates = dyn_states;

    VkPipelineViewportStateCreateInfo vp_state{};
    vp_state.sType = VK_STRUCTURE_TYPE_PIPELINE_VIEWPORT_STATE_CREATE_INFO;
    vp_state.viewportCount = 1;
    vp_state.scissorCount = 1;

    VkPipelineRasterizationStateCreateInfo rast{};
    rast.sType = VK_STRUCTURE_TYPE_PIPELINE_RASTERIZATION_STATE_CREATE_INFO;
    rast.polygonMode = VK_POLYGON_MODE_FILL;
    rast.cullMode = VK_CULL_MODE_NONE;
    rast.frontFace = VK_FRONT_FACE_CLOCKWISE;
    rast.lineWidth = 1.0f;

    VkPipelineMultisampleStateCreateInfo ms{};
    ms.sType = VK_STRUCTURE_TYPE_PIPELINE_MULTISAMPLE_STATE_CREATE_INFO;
    ms.rasterizationSamples = VK_SAMPLE_COUNT_1_BIT;

    VkPipelineColorBlendAttachmentState blend_att{};
    blend_att.colorWriteMask =
        VK_COLOR_COMPONENT_R_BIT | VK_COLOR_COMPONENT_G_BIT | VK_COLOR_COMPONENT_B_BIT | VK_COLOR_COMPONENT_A_BIT;
    blend_att.blendEnable = VK_FALSE;

    VkPipelineColorBlendStateCreateInfo blend{};
    blend.sType = VK_STRUCTURE_TYPE_PIPELINE_COLOR_BLEND_STATE_CREATE_INFO;
    blend.attachmentCount = 1;
    blend.pAttachments = &blend_att;

    VkPipelineLayoutCreateInfo layout_ci{};
    layout_ci.sType = VK_STRUCTURE_TYPE_PIPELINE_LAYOUT_CREATE_INFO;
    if (vkCreatePipelineLayout(m_dev, &layout_ci, nullptr, &m_pipe_layout) != VK_SUCCESS)
        throw std::runtime_error("[Vis] vkCreatePipelineLayout failed");

    VkGraphicsPipelineCreateInfo pipe_ci{};
    pipe_ci.sType = VK_STRUCTURE_TYPE_GRAPHICS_PIPELINE_CREATE_INFO;
    pipe_ci.stageCount = 2;
    pipe_ci.pStages = stages;
    pipe_ci.pVertexInputState = &vert_input;
    pipe_ci.pInputAssemblyState = &ia;
    pipe_ci.pViewportState = &vp_state;
    pipe_ci.pRasterizationState = &rast;
    pipe_ci.pMultisampleState = &ms;
    pipe_ci.pColorBlendState = &blend;
    pipe_ci.pDynamicState = &dyn_state;
    pipe_ci.layout = m_pipe_layout;
    pipe_ci.renderPass = m_render_pass;
    pipe_ci.subpass = 0;

    if (vkCreateGraphicsPipelines(m_dev, VK_NULL_HANDLE, 1, &pipe_ci, nullptr, &m_pipeline) != VK_SUCCESS)
        throw std::runtime_error("[Vis] vkCreateGraphicsPipelines failed");

    vkDestroyShaderModule(m_dev, vert, nullptr);
    vkDestroyShaderModule(m_dev, frag, nullptr);
}

// ---------------------------------------------------------------------------
inline void HandVisualizer::createFramebuffers()
{
    m_framebuffers.resize(m_sc_views.size());
    for (size_t i = 0; i < m_sc_views.size(); ++i)
    {
        VkFramebufferCreateInfo fb_ci{};
        fb_ci.sType = VK_STRUCTURE_TYPE_FRAMEBUFFER_CREATE_INFO;
        fb_ci.renderPass = m_render_pass;
        fb_ci.attachmentCount = 1;
        fb_ci.pAttachments = &m_sc_views[i];
        fb_ci.width = m_sc_extent.width;
        fb_ci.height = m_sc_extent.height;
        fb_ci.layers = 1;

        if (vkCreateFramebuffer(m_dev, &fb_ci, nullptr, &m_framebuffers[i]) != VK_SUCCESS)
            throw std::runtime_error("[Vis] vkCreateFramebuffer failed");
    }
}

// ---------------------------------------------------------------------------
inline void HandVisualizer::createCommandBuffers()
{
    VkCommandPoolCreateInfo pool_ci{};
    pool_ci.sType = VK_STRUCTURE_TYPE_COMMAND_POOL_CREATE_INFO;
    pool_ci.queueFamilyIndex = m_qfam;
    pool_ci.flags = VK_COMMAND_POOL_CREATE_RESET_COMMAND_BUFFER_BIT;

    if (vkCreateCommandPool(m_dev, &pool_ci, nullptr, &m_cmd_pool) != VK_SUCCESS)
        throw std::runtime_error("[Vis] vkCreateCommandPool failed");

    m_cmd_bufs.resize(m_sc_images.size());
    VkCommandBufferAllocateInfo alloc_info{};
    alloc_info.sType = VK_STRUCTURE_TYPE_COMMAND_BUFFER_ALLOCATE_INFO;
    alloc_info.commandPool = m_cmd_pool;
    alloc_info.level = VK_COMMAND_BUFFER_LEVEL_PRIMARY;
    alloc_info.commandBufferCount = static_cast<uint32_t>(m_cmd_bufs.size());

    if (vkAllocateCommandBuffers(m_dev, &alloc_info, m_cmd_bufs.data()) != VK_SUCCESS)
        throw std::runtime_error("[Vis] vkAllocateCommandBuffers failed");
}

// ---------------------------------------------------------------------------
inline void HandVisualizer::createSyncObjects()
{
    VkSemaphoreCreateInfo sem_ci{};
    sem_ci.sType = VK_STRUCTURE_TYPE_SEMAPHORE_CREATE_INFO;

    VkFenceCreateInfo fence_ci{};
    fence_ci.sType = VK_STRUCTURE_TYPE_FENCE_CREATE_INFO;
    fence_ci.flags = VK_FENCE_CREATE_SIGNALED_BIT;

    if (vkCreateSemaphore(m_dev, &sem_ci, nullptr, &m_sem_image_avail) != VK_SUCCESS ||
        vkCreateSemaphore(m_dev, &sem_ci, nullptr, &m_sem_render_done) != VK_SUCCESS ||
        vkCreateFence(m_dev, &fence_ci, nullptr, &m_fence_in_flight) != VK_SUCCESS)
        throw std::runtime_error("[Vis] Failed to create sync objects");
}

// ---------------------------------------------------------------------------
inline void HandVisualizer::createVertexBuffer()
{
    VkDeviceSize size = sizeof(Vertex) * kMaxVertices;

    VkBufferCreateInfo buf_ci{};
    buf_ci.sType = VK_STRUCTURE_TYPE_BUFFER_CREATE_INFO;
    buf_ci.size = size;
    buf_ci.usage = VK_BUFFER_USAGE_VERTEX_BUFFER_BIT;
    buf_ci.sharingMode = VK_SHARING_MODE_EXCLUSIVE;

    if (vkCreateBuffer(m_dev, &buf_ci, nullptr, &m_vbuf) != VK_SUCCESS)
        throw std::runtime_error("[Vis] vkCreateBuffer failed");

    VkMemoryRequirements mem_req{};
    vkGetBufferMemoryRequirements(m_dev, m_vbuf, &mem_req);

    VkPhysicalDeviceMemoryProperties mem_props{};
    vkGetPhysicalDeviceMemoryProperties(m_pdev, &mem_props);

    uint32_t mem_type = UINT32_MAX;
    const uint32_t required = VK_MEMORY_PROPERTY_HOST_VISIBLE_BIT | VK_MEMORY_PROPERTY_HOST_COHERENT_BIT;
    for (uint32_t i = 0; i < mem_props.memoryTypeCount; ++i)
    {
        if ((mem_req.memoryTypeBits & (1u << i)) && (mem_props.memoryTypes[i].propertyFlags & required) == required)
        {
            mem_type = i;
            break;
        }
    }
    if (mem_type == UINT32_MAX)
        throw std::runtime_error("[Vis] No suitable host-visible memory type");

    VkMemoryAllocateInfo alloc_info{};
    alloc_info.sType = VK_STRUCTURE_TYPE_MEMORY_ALLOCATE_INFO;
    alloc_info.allocationSize = mem_req.size;
    alloc_info.memoryTypeIndex = mem_type;

    if (vkAllocateMemory(m_dev, &alloc_info, nullptr, &m_vbuf_mem) != VK_SUCCESS)
        throw std::runtime_error("[Vis] vkAllocateMemory failed");

    vkBindBufferMemory(m_dev, m_vbuf, m_vbuf_mem, 0);
    vkMapMemory(m_dev, m_vbuf_mem, 0, size, 0, &m_vbuf_ptr);
}

// ---------------------------------------------------------------------------
inline void HandVisualizer::destroySwapchainResources()
{
    // Command buffers are allocated from m_cmd_pool sized to the swapchain
    // image count, so the pool's lifetime is tied to the swapchain.
    if (m_cmd_pool)
    {
        vkDestroyCommandPool(m_dev, m_cmd_pool, nullptr);
        m_cmd_pool = VK_NULL_HANDLE;
        m_cmd_bufs.clear();
    }
    for (auto fb : m_framebuffers)
        if (fb)
            vkDestroyFramebuffer(m_dev, fb, nullptr);
    m_framebuffers.clear();
    for (auto iv : m_sc_views)
        if (iv)
            vkDestroyImageView(m_dev, iv, nullptr);
    m_sc_views.clear();
    if (m_swapchain)
    {
        vkDestroySwapchainKHR(m_dev, m_swapchain, nullptr);
        m_swapchain = VK_NULL_HANDLE;
    }
}

// ---------------------------------------------------------------------------
inline std::pair<float, float> HandVisualizer::project(const ManusVec3& p, ProjectionMode mode)
{
    if (mode == ProjectionMode::Top)
        return { p.x, -p.z }; // top-down: X right, -Z up (fingers away from wrist)
    else
        return { -p.z, p.y }; // side (along thumb-axis +X): -Z right, Y up
}

// ---------------------------------------------------------------------------
inline bool HandVisualizer::computeBbox3D(
    const std::vector<SkeletonNode>& nodes, float& xmin, float& xmax, float& ymin, float& ymax, float& zmin, float& zmax)
{
    if (nodes.empty())
        return false;
    xmin = ymin = zmin = std::numeric_limits<float>::max();
    xmax = ymax = zmax = -std::numeric_limits<float>::max();
    for (auto& n : nodes)
    {
        const auto& p = n.transform.position;
        xmin = std::min(xmin, p.x);
        xmax = std::max(xmax, p.x);
        ymin = std::min(ymin, p.y);
        ymax = std::max(ymax, p.y);
        zmin = std::min(zmin, p.z);
        zmax = std::max(zmax, p.z);
    }
    return true;
}

// ---------------------------------------------------------------------------
inline void HandVisualizer::buildHandGeometry(const std::vector<SkeletonNode>& nodes,
                                              const std::vector<NodeInfo>& info,
                                              const std::array<float, 3>& colour,
                                              ProjectionMode mode,
                                              float scale,
                                              float cx,
                                              float cy,
                                              float cz,
                                              float ndc_cx,
                                              float ndc_cy,
                                              std::vector<Vertex>& verts)
{
    if (nodes.empty())
        return;

    // Project the 3-D world center for this view
    ManusVec3 center3d;
    center3d.x = cx;
    center3d.y = cy;
    center3d.z = cz;
    auto [world_cx, world_cy] = project(center3d, mode);

    // Build fast id -> projected-position lookup
    std::unordered_map<uint32_t, std::pair<float, float>> pos_map;
    pos_map.reserve(nodes.size());
    for (auto& n : nodes)
        pos_map[n.id] = project(n.transform.position, mode);

    // Map projected coords -> NDC in this quadrant
    auto to_ndc = [&](const std::pair<float, float>& proj) -> std::pair<float, float>
    {
        float nx = (proj.first - world_cx) * scale + ndc_cx;
        float ny = -(proj.second - world_cy) * scale + ndc_cy; // +Y up on screen
        return { nx, ny };
    };

    float r = colour[0], g = colour[1], b = colour[2];

    // Bones: line from parent to child
    for (auto& ni : info)
    {
        // Skip only the true root (self-referencing: parentId == nodeId).
        // Do NOT skip parentId==0 unconditionally — that would drop CMC-to-wrist edges
        // when the wrist's nodeId happens to be 0.
        if (ni.parentId == ni.nodeId)
            continue;
        auto it_child = pos_map.find(ni.nodeId);
        auto it_parent = pos_map.find(ni.parentId);
        if (it_child == pos_map.end() || it_parent == pos_map.end())
            continue;

        auto [cx2, cy2] = to_ndc(it_child->second);
        auto [px2, py2] = to_ndc(it_parent->second);
        verts.push_back({ cx2, cy2, r, g, b });
        verts.push_back({ px2, py2, r, g, b });
    }

    // Joint markers: small "+" cross at each node
    for (auto& n : nodes)
    {
        auto [nx2, ny2] = to_ndc(pos_map.at(n.id));
        // Horizontal arm
        verts.push_back({ nx2 - kCrossSize, ny2, r, g, b });
        verts.push_back({ nx2 + kCrossSize, ny2, r, g, b });
        // Vertical arm
        verts.push_back({ nx2, ny2 - kCrossSize, r, g, b });
        verts.push_back({ nx2, ny2 + kCrossSize, r, g, b });
    }
}

// ---------------------------------------------------------------------------
inline void HandVisualizer::run(ManusTracker& tracker, std::stop_token st)
{
    bool running = true;

    while (running && !st.stop_requested())
    {
        // -- Poll X11 events -------------------------------------------------
        while (XPending(m_dpy))
        {
            XEvent ev;
            XNextEvent(m_dpy, &ev);
            if (ev.type == ClientMessage && static_cast<Atom>(ev.xclient.data.l[0]) == m_wm_del)
            {
                running = false;
            }
            if (ev.type == KeyPress)
                running = false;
        }
        if (!running)
            break;

        // -- Build geometry --------------------------------------------------
        auto left_nodes = tracker.get_left_hand_nodes();
        auto right_nodes = tracker.get_right_hand_nodes();
        auto left_info = tracker.get_left_node_info();
        auto right_info = tracker.get_right_node_info();

        std::vector<Vertex> verts;
        verts.reserve(1024);

        // Separator lines between the 4 quadrants (dim grey)
        constexpr float kG = 0.20f;
        verts.push_back({ -1.0f, 0.0f, kG, kG, kG });
        verts.push_back({ 1.0f, 0.0f, kG, kG, kG }); // horizontal
        verts.push_back({ 0.0f, 1.0f, kG, kG, kG });
        verts.push_back({ 0.0f, -1.0f, kG, kG, kG }); // vertical

        // Per-hand scale locked on first data frame from 3-D bbox max extent,
        // shared between Top and Side panels so both are at the same magnification.
        // Reset when glove disconnects so it recalibrates on reconnect.
        auto fit_scale3d = [](float xn, float xx, float yn, float yx, float zn, float zx) -> float {
            return 0.85f / std::max({ xx - xn, yx - yn, zx - zn, 0.001f });
        };

        float lxmin, lxmax, lymin, lymax, lzmin, lzmax;
        const bool has_left = computeBbox3D(left_nodes, lxmin, lxmax, lymin, lymax, lzmin, lzmax);
        if (!has_left)
            m_left_state = {};
        else if (m_left_state.scale == 0.0f)
        {
            m_left_state.scale = fit_scale3d(lxmin, lxmax, lymin, lymax, lzmin, lzmax);
            m_left_state.cx = (lxmin + lxmax) * 0.5f;
            m_left_state.cy = (lymin + lymax) * 0.5f;
            m_left_state.cz = (lzmin + lzmax) * 0.5f;
        }

        float rxmin, rxmax, rymin, rymax, rzmin, rzmax;
        const bool has_right = computeBbox3D(right_nodes, rxmin, rxmax, rymin, rymax, rzmin, rzmax);
        if (!has_right)
            m_right_state = {};
        else if (m_right_state.scale == 0.0f)
        {
            m_right_state.scale = fit_scale3d(rxmin, rxmax, rymin, rymax, rzmin, rzmax);
            m_right_state.cx = (rxmin + rxmax) * 0.5f;
            m_right_state.cy = (rymin + rymax) * 0.5f;
            m_right_state.cz = (rzmin + rzmax) * 0.5f;
        }

        // 4-quadrant layout:
        //   Top-left    (-0.5,+0.5): left  hand — top-down (XZ)
        //   Bottom-left (-0.5,-0.5): left  hand — side (ZY, thumb axis)
        //   Top-right   (+0.5,+0.5): right hand — top-down
        //   Bottom-right(+0.5,-0.5): right hand — side
        if (has_left)
        {
            buildHandGeometry(left_nodes, left_info, kLeftColor, ProjectionMode::Top, m_left_state.scale,
                              m_left_state.cx, m_left_state.cy, m_left_state.cz, -0.5f, +0.5f, verts);
            buildHandGeometry(left_nodes, left_info, kLeftColor, ProjectionMode::Side, m_left_state.scale,
                              m_left_state.cx, m_left_state.cy, m_left_state.cz, -0.5f, -0.5f, verts);
        }
        if (has_right)
        {
            buildHandGeometry(right_nodes, right_info, kRightColor, ProjectionMode::Top, m_right_state.scale,
                              m_right_state.cx, m_right_state.cy, m_right_state.cz, +0.5f, +0.5f, verts);
            buildHandGeometry(right_nodes, right_info, kRightColor, ProjectionMode::Side, m_right_state.scale,
                              m_right_state.cx, m_right_state.cy, m_right_state.cz, +0.5f, -0.5f, verts);
        }

        // -- Upload vertices -------------------------------------------------
        uint32_t vert_count = static_cast<uint32_t>(std::min<size_t>(verts.size(), kMaxVertices));

        if (vert_count > 0)
            std::memcpy(m_vbuf_ptr, verts.data(), vert_count * sizeof(Vertex));

        // -- Render frame ----------------------------------------------------
        // Wait for the previous frame's fence before touching per-frame state.
        // Do NOT reset the fence yet — if vkAcquireNextImageKHR fails we will
        // continue without submitting, and the fence must stay signaled so the
        // next iteration's vkWaitForFences returns immediately.
        vkWaitForFences(m_dev, 1, &m_fence_in_flight, VK_TRUE, UINT64_MAX);

        uint32_t img_idx = 0;
        VkResult acquire_result =
            vkAcquireNextImageKHR(m_dev, m_swapchain, UINT64_MAX, m_sem_image_avail, VK_NULL_HANDLE, &img_idx);

        if (acquire_result == VK_ERROR_OUT_OF_DATE_KHR)
        {
            vkDeviceWaitIdle(m_dev);
            destroySwapchainResources();
            createSwapchain();
            createFramebuffers();
            createCommandBuffers();
            // Fence is still signaled — leave it so the next vkWaitForFences
            // returns immediately without us having submitted anything.
            continue;
        }

        // Acquisition succeeded: safe to reset the fence now so we can use it
        // as the submit signal for this frame.
        vkResetFences(m_dev, 1, &m_fence_in_flight);

        // Record command buffer
        VkCommandBuffer cmd = m_cmd_bufs[img_idx];
        vkResetCommandBuffer(cmd, 0);

        VkCommandBufferBeginInfo begin_info{};
        begin_info.sType = VK_STRUCTURE_TYPE_COMMAND_BUFFER_BEGIN_INFO;
        vkBeginCommandBuffer(cmd, &begin_info);

        VkClearValue clear_val{};
        clear_val.color = { { 0.0f, 0.0f, 0.0f, 1.0f } }; // black background

        VkRenderPassBeginInfo rp_begin{};
        rp_begin.sType = VK_STRUCTURE_TYPE_RENDER_PASS_BEGIN_INFO;
        rp_begin.renderPass = m_render_pass;
        rp_begin.framebuffer = m_framebuffers[img_idx];
        rp_begin.renderArea.extent = m_sc_extent;
        rp_begin.clearValueCount = 1;
        rp_begin.pClearValues = &clear_val;

        vkCmdBeginRenderPass(cmd, &rp_begin, VK_SUBPASS_CONTENTS_INLINE);
        vkCmdBindPipeline(cmd, VK_PIPELINE_BIND_POINT_GRAPHICS, m_pipeline);

        VkViewport vp{};
        vp.width = static_cast<float>(m_sc_extent.width);
        vp.height = static_cast<float>(m_sc_extent.height);
        vp.minDepth = 0.0f;
        vp.maxDepth = 1.0f;
        vkCmdSetViewport(cmd, 0, 1, &vp);

        VkRect2D scissor{};
        scissor.extent = m_sc_extent;
        vkCmdSetScissor(cmd, 0, 1, &scissor);

        if (vert_count > 0)
        {
            VkDeviceSize offset = 0;
            vkCmdBindVertexBuffers(cmd, 0, 1, &m_vbuf, &offset);
            vkCmdDraw(cmd, vert_count, 1, 0, 0);
        }

        vkCmdEndRenderPass(cmd);
        vkEndCommandBuffer(cmd);

        // Submit
        VkPipelineStageFlags wait_stage = VK_PIPELINE_STAGE_COLOR_ATTACHMENT_OUTPUT_BIT;
        VkSubmitInfo submit_info{};
        submit_info.sType = VK_STRUCTURE_TYPE_SUBMIT_INFO;
        submit_info.waitSemaphoreCount = 1;
        submit_info.pWaitSemaphores = &m_sem_image_avail;
        submit_info.pWaitDstStageMask = &wait_stage;
        submit_info.commandBufferCount = 1;
        submit_info.pCommandBuffers = &cmd;
        submit_info.signalSemaphoreCount = 1;
        submit_info.pSignalSemaphores = &m_sem_render_done;

        vkQueueSubmit(m_queue, 1, &submit_info, m_fence_in_flight);

        // Present
        VkPresentInfoKHR present_info{};
        present_info.sType = VK_STRUCTURE_TYPE_PRESENT_INFO_KHR;
        present_info.waitSemaphoreCount = 1;
        present_info.pWaitSemaphores = &m_sem_render_done;
        present_info.swapchainCount = 1;
        present_info.pSwapchains = &m_swapchain;
        present_info.pImageIndices = &img_idx;

        VkResult present_result = vkQueuePresentKHR(m_queue, &present_info);
        if (present_result == VK_ERROR_OUT_OF_DATE_KHR || present_result == VK_SUBOPTIMAL_KHR)
        {
            vkDeviceWaitIdle(m_dev);
            destroySwapchainResources();
            createSwapchain();
            createFramebuffers();
            createCommandBuffers();
        }
    }

    vkDeviceWaitIdle(m_dev);
}

} // namespace manus
} // namespace plugins
