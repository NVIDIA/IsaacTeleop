// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#pragma once

// The compiled scene, owned here rather than by a `mujoco` wheel in the caller's
// environment. That ownership is what makes the private MuJoCo an implementation detail:
// nothing outside this module allocates an mjModel, so there is no second copy's field
// layout to agree with. Python reaches the arrays through
// zero-copy numpy views handed out by the bindings.

#include <mujoco/mujoco.h>

#include <string>

namespace robot_twin
{

class Scene
{
public:
    // Compiles `path`. Throws std::runtime_error carrying MuJoCo's own parse error.
    explicit Scene(const std::string& path);
    ~Scene();

    Scene(const Scene&) = delete;
    Scene& operator=(const Scene&) = delete;

    mjModel* model()
    {
        return model_;
    }
    const mjModel* model() const
    {
        return model_;
    }
    mjData* data()
    {
        return data_;
    }

    // Forward kinematics. The scene is never integrated, so this is what refreshes
    // every derived field a write to qpos / body_* / mocap_* invalidates.
    void forward();

    // -1 when the scene declares no such object.
    int id(mjtObj type, const std::string& name) const;

    // Empty when the object has no name.
    std::string name(mjtObj type, int index) const;

private:
    mjModel* model_ = nullptr;
    mjData* data_ = nullptr;
};

} // namespace robot_twin
