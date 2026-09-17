// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0
//
// Every MuJoCo entry point this module calls, resolved by mj_api.cpp against the private
// libisaacteleop_mujoco.so. FN entries are functions. VAR entries are MuJoCo's global
// hook variables, so `mujoco::name` is a pointer TO the variable and call sites deref it.
//
// No include guard, deliberately: mj_api.hpp and mj_api.cpp include this three times over
// with the macros defined differently -- declare, define, resolve -- so no two lists can
// drift and leave an entry point null at the first call.

ROBOT_TWIN_MJ_FN(mj_version)
ROBOT_TWIN_MJ_FN(mj_versionString)
ROBOT_TWIN_MJ_FN(mj_loadXML)
ROBOT_TWIN_MJ_FN(mj_makeData)
ROBOT_TWIN_MJ_FN(mj_deleteData)
ROBOT_TWIN_MJ_FN(mj_deleteModel)
ROBOT_TWIN_MJ_FN(mj_kinematics)
ROBOT_TWIN_MJ_FN(mj_camlight)
ROBOT_TWIN_MJ_FN(mj_name2id)
ROBOT_TWIN_MJ_FN(mj_id2name)

ROBOT_TWIN_MJ_FN(mju_mulQuat)
ROBOT_TWIN_MJ_FN(mju_rotVecQuat)

ROBOT_TWIN_MJ_FN(mjv_defaultOption)
ROBOT_TWIN_MJ_FN(mjv_defaultFreeCamera)
ROBOT_TWIN_MJ_FN(mjv_makeScene)
ROBOT_TWIN_MJ_FN(mjv_freeScene)
ROBOT_TWIN_MJ_FN(mjv_updateScene)

ROBOT_TWIN_MJ_FN(mjr_defaultContext)
ROBOT_TWIN_MJ_FN(mjr_makeContext)
ROBOT_TWIN_MJ_FN(mjr_freeContext)
ROBOT_TWIN_MJ_FN(mjr_resizeOffscreen)
ROBOT_TWIN_MJ_FN(mjr_setBuffer)
ROBOT_TWIN_MJ_FN(mjr_render)

ROBOT_TWIN_MJ_VAR(mju_user_error)
ROBOT_TWIN_MJ_VAR(mju_user_warning)
