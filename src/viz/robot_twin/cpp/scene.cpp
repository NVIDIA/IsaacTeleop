// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#include "scene.hpp"

#include "mj_api.hpp"
#include "mj_guard.hpp"

#include <stdexcept>

namespace robot_twin
{

Scene::Scene(const std::string& path)
{
    // mj_loadXML reports parse failures through this buffer rather than mju_error, and
    // 1 kB is what MuJoCo's own callers give it.
    char error[1024] = { 0 };
    model_ = mujoco::mj_loadXML(path.c_str(), nullptr, error, sizeof(error));
    if (model_ == nullptr)
    {
        throw std::runtime_error(std::string("robot_twin: ") + error);
    }
    // ~Scene does not run when a constructor throws, so everything past the mjModel is
    // wrapped: guarded() throws on an mju_user_error, and so does forward().
    try
    {
        guarded("mj_makeData", [this] { data_ = mujoco::mj_makeData(model_); });
        if (data_ == nullptr)
        {
            throw std::runtime_error("robot_twin: mj_makeData returned nothing");
        }
        forward();
    }
    catch (...)
    {
        if (data_ != nullptr)
        {
            mujoco::mj_deleteData(data_);
            data_ = nullptr;
        }
        mujoco::mj_deleteModel(model_);
        model_ = nullptr;
        throw;
    }
}

Scene::~Scene()
{
    if (data_ != nullptr)
    {
        mujoco::mj_deleteData(data_);
    }
    if (model_ != nullptr)
    {
        mujoco::mj_deleteModel(model_);
    }
}

void Scene::forward()
{
    // The position stage of mj_forward and nothing else. Collision, constraints, inertia,
    // actuation and sensors are dynamics: this scene is never integrated, so computing
    // them would be work no pixel reads.
    guarded("mj_kinematics", [this] { mujoco::mj_kinematics(model_, data_); });
    guarded("mj_camlight", [this] { mujoco::mj_camlight(model_, data_); });
}

int Scene::id(mjtObj type, const std::string& name) const
{
    return mujoco::mj_name2id(model_, type, name.c_str());
}

std::string Scene::name(mjtObj type, int index) const
{
    const char* found = mujoco::mj_id2name(model_, type, index);
    return found == nullptr ? std::string() : std::string(found);
}

} // namespace robot_twin
