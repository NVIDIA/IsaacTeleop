// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0
//
// A minimum robot-twin backend: enough MuJoCo to prove the recipe works and stays
// invisible. test_symbol_isolation.py is the assertion; this is only its subject.
//
// It resolves MuJoCo itself rather than reusing robot_twin/cpp/mj_api.cpp, and that
// independence is the point -- a shared loader could not fail this test and the shipped
// module at the same time. What the two must keep in common (dlopen by our own path,
// RTLD_LOCAL, no undefined mj*) is stated in cmake/Mujoco.cmake.

#include <mujoco/mujoco.h>
#include <pybind11/pybind11.h>

#include <csetjmp>
#include <cstdlib>
#include <dlfcn.h>
#include <stdexcept>
#include <string>

namespace
{

// Resolving the renderer entry points, which this probe never calls (it has no GL
// context), is what proves the private library carries a working renderer build.
#define PROBE_MJ_FUNCTIONS(X)                                                                                          \
    X(mj_versionString)                                                                                                \
    X(mj_loadXML)                                                                                                      \
    X(mj_makeData)                                                                                                     \
    X(mj_deleteData)                                                                                                   \
    X(mj_deleteModel)                                                                                                  \
    X(mj_forward)                                                                                                      \
    X(mju_error)                                                                                                       \
    X(mjv_defaultScene)                                                                                                \
    X(mjv_makeScene)                                                                                                   \
    X(mjv_freeScene)                                                                                                   \
    X(mjv_defaultOption)                                                                                               \
    X(mjv_defaultFreeCamera)                                                                                           \
    X(mjv_updateScene)                                                                                                 \
    X(mjr_makeContext)                                                                                                 \
    X(mjr_render)                                                                                                      \
    X(mjr_setBuffer)                                                                                                   \
    X(mjr_readPixels)                                                                                                  \
    X(mjr_resizeOffscreen)

#define PROBE_MJ_DECLARE(name) decltype(::name)* p_##name = nullptr;
PROBE_MJ_FUNCTIONS(PROBE_MJ_DECLARE)
#undef PROBE_MJ_DECLARE

// MuJoCo's mju_user_error hook: a variable, so this is a pointer TO it.
decltype(::mju_user_error)* p_mju_user_error = nullptr;

const char kAnchor = 0;

template <typename T>
void resolve(void* handle, T& out, const char* name)
{
    void* symbol = dlsym(handle, name);
    if (symbol == nullptr)
    {
        throw std::runtime_error(std::string("mujoco_probe: no ") + name);
    }
    out = reinterpret_cast<T>(symbol);
}

// The copy beside this extension, by this extension's own path, RTLD_LOCAL so its mj*
// never reach the global scope.
void load()
{
    Dl_info info{};
    if (dladdr(&kAnchor, &info) == 0 || info.dli_fname == nullptr)
    {
        throw std::runtime_error("mujoco_probe: dladdr cannot name this extension's file");
    }
    std::string path(info.dli_fname);
    const std::size_t slash = path.rfind('/');
    path.erase(slash == std::string::npos ? 0 : slash + 1);
    path += "libisaacteleop_mujoco.so";

    void* handle = dlopen(path.c_str(), RTLD_NOW | RTLD_LOCAL);
    if (handle == nullptr)
    {
        const char* why = dlerror();
        throw std::runtime_error("mujoco_probe: cannot open " + path + ": " + (why == nullptr ? "" : why));
    }

#define PROBE_MJ_RESOLVE(name) resolve(handle, p_##name, #name);
    PROBE_MJ_FUNCTIONS(PROBE_MJ_RESOLVE)
#undef PROBE_MJ_RESOLVE
    resolve(handle, p_mju_user_error, "mju_user_error");
}

// MuJoCo's default error handler calls exit(), and one that RETURNS is worse: the caller
// resumes on invalid state. Throwing is not the answer either -- whether the exception
// reaches a catch depends on LTO settings, measured here on two builds differing only in
// MUJOCO_ENABLE_LTO. longjmp is what MuJoCo's own comment prescribes and needs no unwind
// tables. Only MuJoCo's C frames are skipped, so nothing with a destructor is leaked.
thread_local std::jmp_buf g_recover;
thread_local bool g_armed = false;
thread_local std::string g_message;

void recover_from_mujoco(const char* message)
{
    g_message = message;
    if (!g_armed)
    {
        // No guard on this call path: a core dump beats running on invalid state.
        std::abort();
    }
    g_armed = false;
    std::longjmp(g_recover, 1);
}

// Version of the copy this extension loaded, not of any installed wheel.
std::string version()
{
    return p_mj_versionString();
}

// Parses a model and builds a scene: tinyxml2, qhull, ccd and the visualizer, minus GL.
int scene_geoms(const std::string& path)
{
    char error[1024] = { 0 };
    mjModel* model = p_mj_loadXML(path.c_str(), nullptr, error, sizeof(error));
    if (!model)
    {
        throw std::runtime_error(error);
    }
    mjData* data = p_mj_makeData(model);
    mjvScene scene;
    p_mjv_defaultScene(&scene);
    p_mjv_makeScene(model, &scene, 1000);
    mjvOption option;
    p_mjv_defaultOption(&option);
    mjvCamera camera;
    p_mjv_defaultFreeCamera(model, &camera);
    p_mj_forward(model, data);
    p_mjv_updateScene(model, data, &option, nullptr, &camera, mjCAT_ALL, &scene);
    const int ngeom = scene.ngeom;
    p_mjv_freeScene(&scene);
    p_mj_deleteData(data);
    p_mj_deleteModel(model);
    return ngeom;
}

// Round-trips mju_error through the handler above, so the test can see it did not exit.
std::string recovered_message()
{
    if (setjmp(g_recover) != 0)
    {
        return "mujoco: " + g_message;
    }
    g_armed = true;
    p_mju_error("probe: deliberate");
    g_armed = false;
    return "handler returned -- MuJoCo would have continued with invalid state";
}

} // namespace

PYBIND11_MODULE(_mujoco_probe, m)
{
    load();
    *p_mju_user_error = recover_from_mujoco;
    m.def("version", &version);
    m.def("scene_geoms", &scene_geoms);
    m.def("recovered_message", &recovered_message);
}
