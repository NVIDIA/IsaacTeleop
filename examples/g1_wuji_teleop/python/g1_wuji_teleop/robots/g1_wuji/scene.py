# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Isaac Lab scene helpers for the G1-Wuji teleop app."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class G1WujiSceneConfig:
    robot_prim: str
    robot_usd: Path
    initial_world_position: tuple[float, float, float]
    initial_world_orientation_xyzw: tuple[float, float, float, float]
    initial_hand_joint_positions: Mapping[str, float]
    light_intensity: float


def make_g1_wuji_robot_cfg(config: G1WujiSceneConfig):
    import isaaclab.sim as sim_utils
    from isaaclab.actuators import ImplicitActuatorCfg
    from isaaclab.assets import ArticulationCfg

    joint_pos = {
        "right_wrist_yaw_joint": 0.0,
        "left_wrist_yaw_joint": 0.0,
        ".*_wrist_pitch_joint": 0.0,
        ".*_wrist_roll_joint": 0.0,
        ".*_shoulder_pitch_joint": 0.0,
        ".*_shoulder_roll_joint": 0.0,
        ".*_shoulder_yaw_joint": 0.0,
        "right_elbow_joint": 0.0,
        "left_elbow_joint": 0.0,
    }
    joint_pos.update(
        {
            name: float(value)
            for name, value in config.initial_hand_joint_positions.items()
        }
    )

    return ArticulationCfg(
        prim_path=config.robot_prim,
        spawn=sim_utils.UsdFileCfg(
            usd_path=str(config.robot_usd),
            activate_contact_sensors=False,
            rigid_props=sim_utils.RigidBodyPropertiesCfg(
                disable_gravity=True,
                retain_accelerations=False,
                max_linear_velocity=100.0,
                max_angular_velocity=1000.0,
                max_depenetration_velocity=1.0,
            ),
            collision_props=sim_utils.CollisionPropertiesCfg(
                contact_offset=0.002,
                rest_offset=0.001,
            ),
            articulation_props=sim_utils.ArticulationRootPropertiesCfg(
                enabled_self_collisions=False,
                solver_position_iteration_count=16,
                solver_velocity_iteration_count=4,
                sleep_threshold=0.005,
                stabilization_threshold=0.001,
            ),
        ),
        init_state=ArticulationCfg.InitialStateCfg(
            pos=config.initial_world_position,
            # IsaacLab consumes the articulation root quaternion as [x, y, z, w].
            rot=config.initial_world_orientation_xyzw,
            joint_pos=joint_pos,
            joint_vel={".*": 0.0},
        ),
        soft_joint_pos_limit_factor=0.98,
        actuators=_wuji_actuators(ImplicitActuatorCfg),
    )


def _wuji_actuators(ImplicitActuatorCfg):
    common = {
        "base": ImplicitActuatorCfg(
            joint_names_expr=["base_.*"],
            effort_limit_sim=100000.0,
            velocity_limit_sim=1000.0,
            stiffness=1e6,
            damping=1e4,
        ),
        "right_arm": ImplicitActuatorCfg(
            joint_names_expr=["right_shoulder_.*", "right_elbow_joint"],
            effort_limit_sim=5.0,
            velocity_limit_sim=3.0,
            stiffness=400.0,
            damping=80.0,
        ),
        "left_arm": ImplicitActuatorCfg(
            joint_names_expr=["left_shoulder_.*", "left_elbow_joint"],
            effort_limit_sim=5.0,
            velocity_limit_sim=3.0,
            stiffness=400.0,
            damping=80.0,
        ),
        "wrist": ImplicitActuatorCfg(
            joint_names_expr=[
                "left_wrist_roll_joint",
                "left_wrist_pitch_joint",
                "left_wrist_yaw_joint",
                "right_wrist_roll_joint",
                "right_wrist_pitch_joint",
                "right_wrist_yaw_joint",
            ],
            effort_limit_sim=90000.0,
            velocity_limit_sim=1200.0,
            stiffness=400.0,
            damping=80.0,
        ),
    }
    common["fingers"] = ImplicitActuatorCfg(
        joint_names_expr=["left_finger.*", "right_finger.*"],
        effort_limit_sim=300.0,
        velocity_limit_sim=8.0,
        stiffness=4000.0,
        damping=120.0,
    )
    return common


def design_g1_wuji_scene(config: G1WujiSceneConfig) -> Any:
    import isaaclab.sim as sim_utils
    from isaaclab.assets import Articulation

    graspable_surface_material = sim_utils.RigidBodyMaterialCfg(
        static_friction=1.3,
        dynamic_friction=1.1,
        restitution=0.0,
        friction_combine_mode="max",
        restitution_combine_mode="min",
    )

    floor_cfg = sim_utils.CuboidCfg(
        size=(6.0, 6.0, 0.04),
        collision_props=sim_utils.CollisionPropertiesCfg(),
        visual_material=sim_utils.PreviewSurfaceCfg(
            diffuse_color=(0.25, 0.25, 0.25), roughness=0.8
        ),
    )
    floor_cfg.func("/World/Floor", floor_cfg, translation=(0.0, 0.0, -0.02))

    table_color = (0.54, 0.42, 0.30)
    table_leg_color = (0.22, 0.22, 0.24)
    table_top_size = (1.20, 0.75, 0.05)
    table_top_center = (0.0, 0.5, 0.74)
    table_leg_size = (0.06, 0.06, 0.72)
    table_leg_x_offset = table_top_size[0] * 0.5 - 0.09
    table_leg_y_offset = table_top_size[1] * 0.5 - 0.09
    table_leg_z = table_leg_size[2] * 0.5

    table_top_cfg = sim_utils.CuboidCfg(
        size=table_top_size,
        collision_props=sim_utils.CollisionPropertiesCfg(),
        physics_material=graspable_surface_material,
        visual_material=sim_utils.PreviewSurfaceCfg(
            diffuse_color=table_color,
            roughness=0.55,
        ),
    )
    table_top_cfg.func(
        "/World/Props/TableTop", table_top_cfg, translation=table_top_center
    )

    table_leg_cfg = sim_utils.CuboidCfg(
        size=table_leg_size,
        collision_props=sim_utils.CollisionPropertiesCfg(),
        physics_material=graspable_surface_material,
        visual_material=sim_utils.PreviewSurfaceCfg(
            diffuse_color=table_leg_color,
            roughness=0.65,
        ),
    )
    for leg_index, (x_sign, y_sign) in enumerate(
        ((1.0, 1.0), (1.0, -1.0), (-1.0, 1.0), (-1.0, -1.0)), start=1
    ):
        table_leg_cfg.func(
            f"/World/Props/TableLeg{leg_index}",
            table_leg_cfg,
            translation=(
                table_top_center[0] + x_sign * table_leg_x_offset,
                table_top_center[1] + y_sign * table_leg_y_offset,
                table_leg_z,
            ),
        )

    cylinder_radius = 0.032
    cylinder_height = 0.18
    cylinder_surface_z = table_top_center[2] + table_top_size[2] * 0.5
    cylinder_cfg = sim_utils.CylinderCfg(
        radius=cylinder_radius,
        height=cylinder_height,
        axis="Z",
        collision_props=sim_utils.CollisionPropertiesCfg(
            contact_offset=0.003,
            rest_offset=0.0,
        ),
        rigid_props=sim_utils.RigidBodyPropertiesCfg(
            rigid_body_enabled=True,
            kinematic_enabled=False,
            disable_gravity=False,
            linear_damping=0.08,
            angular_damping=0.06,
            max_linear_velocity=8.0,
            max_angular_velocity=50.0,
            max_depenetration_velocity=3.0,
            solver_position_iteration_count=16,
            solver_velocity_iteration_count=4,
            sleep_threshold=0.002,
            stabilization_threshold=0.001,
        ),
        mass_props=sim_utils.MassPropertiesCfg(mass=0.18),
        physics_material=sim_utils.RigidBodyMaterialCfg(
            static_friction=1.4,
            dynamic_friction=1.2,
            restitution=0.0,
            friction_combine_mode="max",
            restitution_combine_mode="min",
        ),
        visual_material=sim_utils.PreviewSurfaceCfg(
            diffuse_color=(0.84, 0.18, 0.10),
            roughness=0.35,
            metallic=0.05,
        ),
    )
    cylinder_cfg.func(
        "/World/Props/GraspCylinder",
        cylinder_cfg,
        translation=(
            table_top_center[0],
            table_top_center[1] - 0.12,
            cylinder_surface_z + cylinder_height * 0.5,
        ),
    )

    light_cfg = sim_utils.DomeLightCfg(
        intensity=config.light_intensity,
        color=(0.75, 0.75, 0.75),
    )
    light_cfg.func("/World/Light", light_cfg)

    return Articulation(cfg=make_g1_wuji_robot_cfg(config))
