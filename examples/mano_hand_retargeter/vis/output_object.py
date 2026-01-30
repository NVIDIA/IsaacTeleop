import os
import imageio
import numpy as np
import torch

from geometry.mesh import make_batch_mesh
from util.tensor import detach_all, move_to

from .fig_specs import get_seq_figure_skip, get_seq_static_lookat_points
from .output import get_static_views  # reuse existing camera view logic


def animate_scene_with_objects(
    vis,
    scene,
    out_name,
    seq_name=None,
    accumulate=False,
    render_views=("src_cam", "front", "above", "side"),
    render_bg=True,
    render_cam=True,
    render_ground=True,
    debug=False,
    render_keypoints=False,
    **kwargs,
):
    """
    Drop-in replacement for vis.output.animate_scene that also renders
    per-frame object meshes stored in scene["objects"].

    The scene dict is expected to contain:
        - "geometry": (verts, joints, colors, l_faces, r_faces, is_right, bounds)
        - "cameras": dict of camera pose sequences
        - optional "ground": ground pose
        - optional "objects": list of length T, each entry is either:
              None,
              a trimesh.Trimesh instance, or
              a list of trimesh.Trimesh instances.
    """
    if len(render_views) < 1:
        return

    scene = build_pyrender_scene_with_objects(
        vis,
        scene,
        seq_name,
        render_views=list(render_views),
        render_cam=render_cam,
        accumulate=accumulate,
        debug=debug,
    )

    print("RENDERING VIEWS", scene["cameras"].keys())
    render_ground = render_ground and "ground" in scene
    save_paths = []
    for cam_name, cam_poses in scene["cameras"].items():
        is_src = cam_name == "src_cam"
        show_bg = is_src and render_bg
        show_ground = render_ground and not is_src
        show_cam = render_cam and not is_src
        show_keypoints = is_src and render_keypoints  # Only show keypoints on source view
        vis_name = f"{out_name}_{cam_name}"
        print(f"{cam_name} has {len(cam_poses)} poses")
        skip = 10 if debug else 1
        vis.set_camera_seq(cam_poses[::skip])
        save_path = vis.animate(
            vis_name,
            render_bg=show_bg,
            render_ground=show_ground,
            render_cam=show_cam,
            render_keypoints=show_keypoints,
            **kwargs,
        )
        save_paths.append(save_path)

    return save_paths


def build_pyrender_scene_with_objects(
    vis,
    scene,
    seq_name,
    render_views=("src_cam", "front", "above", "side"),
    render_cam=True,
    accumulate=False,
    debug=False,
):
    """
    Same as vis.output.build_pyrender_scene, but additionally supports
    per-frame object meshes stored under scene["objects"].
    """
    if len(render_views) < 1:
        return

    assert all(view in ["src_cam", "front", "above", "side"] for view in render_views)

    scene = move_to(detach_all(scene), "cpu")
    src_cams = scene["cameras"]["src_cam"]
    verts, _, colors, l_faces, r_faces, is_right, bounds = scene["geometry"]
    T = len(verts)
    print(f"{T} mesh frames for {seq_name}, {len(verts)}")

    # Optional per-frame object meshes: list length T, each item list[trimesh.Trimesh]
    object_meshes = scene.get("objects", None)

    # set camera views
    if "cameras" not in scene:
        scene["cameras"] = {}

    # remove default views from source camera perspective if desired
    if "src_cam" not in render_views:
        scene["cameras"].pop("src_cam", None)
    if "front" not in render_views:
        scene["cameras"].pop("front", None)

    # add static viewpoints if desired
    top_pose, side_pose, _skip = get_static_views(seq_name, bounds)
    if "above" in render_views:
        scene["cameras"]["above"] = top_pose[None]
    if "side" in render_views:
        scene["cameras"]["side"] = side_pose[None]
    if "front" in render_views:
        # static front camera using scene bounds
        if bounds is not None:
            bb_min, bb_max, center = bounds
            length = torch.abs(bb_max - bb_min).max()
            front_offset = 1.0
            front_source = center + torch.tensor([0.0, -0.5, -front_offset])
            front_target = center
            up = torch.tensor([0.0, 1.0, 0.0])
            from geometry import camera as cam_util

            front_pose = cam_util.lookat_matrix(front_source, front_target, up)
            scene["cameras"]["front"] = front_pose[None]

    # accumulate meshes if possible (can only accumulate for static camera)
    moving_cam = "src_cam" in render_views or "front" in render_views
    accumulate = accumulate and not moving_cam
    skip = _skip if accumulate else 1

    vis.clear_meshes()

    if "ground" in scene:
        vis.set_ground(scene["ground"])

    if debug:
        skip = 10
    times = list(range(0, T, skip))

    for t in times:
        # Hand meshes (same as original build_pyrender_scene)
        if len(is_right[t]) > 1:
            assert is_right[t].cpu().numpy().tolist() == [0, 1]
            l_meshes = make_batch_mesh(verts[t][0][None], l_faces[t], colors[t][0][None])
            r_meshes = make_batch_mesh(verts[t][1][None], r_faces[t], colors[t][1][None])
            assert len(l_meshes) == 1
            assert len(r_meshes) == 1
            meshes = [l_meshes[0], r_meshes[0]]
        else:
            assert len(is_right[t]) == 1
            if is_right[t] == 0:
                meshes = make_batch_mesh(verts[t][0][None], l_faces[t], colors[t][0][None])
            elif is_right[t] == 1:
                meshes = make_batch_mesh(verts[t][0][None], r_faces[t], colors[t][0][None])
            else:
                meshes = []

        # Append object meshes for this frame if provided
        if object_meshes is not None:
            if t < len(object_meshes) and object_meshes[t] is not None:
                if isinstance(object_meshes[t], (list, tuple)):
                    meshes = list(meshes) + list(object_meshes[t])
                else:
                    meshes = list(meshes) + [object_meshes[t]]

        if accumulate:
            vis.add_static_meshes(meshes)
        else:
            vis.add_mesh_frame(meshes, debug=debug)

    # add camera markers
    if render_cam:
        if accumulate:
            vis.add_camera_markers_static(src_cams[::skip])
        else:
            vis.add_camera_markers(src_cams[::skip])

    return scene


