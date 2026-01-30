import torch

from geometry import camera as cam_util
from geometry.mesh import make_batch_mesh

from util.tensor import detach_all, move_to

from .output import get_static_views  # reuse existing per-sequence heuristics


def animate_scene_far(
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
    Drop‑in replacement for vis.output.animate_scene, but with static cameras
    (front/above/side) placed farther from the scene based on the optimized
    source camera trajectory.
    """
    if len(render_views) < 1:
        return

    scene = build_pyrender_scene_far(
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
        show_keypoints = is_src and render_keypoints  # only on src view
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


def build_pyrender_scene_far(
    vis,
    scene,
    seq_name,
    render_views=("src_cam", "front", "above", "side"),
    render_cam=True,
    accumulate=False,
    debug=False,
):
    """
    Same as vis.output.build_pyrender_scene, but:
      - Uses the first optimized source camera pose to define a global direction
      - Places `front`, `above`, and `side` cameras far from the scene center
        along intuitive directions, scaled by the scene size.
    """
    if len(render_views) < 1:
        return

    assert all(view in ["src_cam", "front", "above", "side"] for view in render_views)

    scene = move_to(detach_all(scene), "cpu")
    src_cams = scene["cameras"]["src_cam"]
    verts, _, colors, l_faces, r_faces, is_right, bounds = scene["geometry"]
    T = len(verts)
    print(f"{T} mesh frames for {seq_name}, {len(verts)}")

    # set camera views
    if "cameras" not in scene:
        scene["cameras"] = {}

    # remove default views from source camera perspective if desired
    if "src_cam" not in render_views:
        scene["cameras"].pop("src_cam", None)
    if "front" not in render_views:
        scene["cameras"].pop("front", None)

    # start from the original heuristic top/side views as a fallback
    top_pose, side_pose, _skip = get_static_views(seq_name, bounds)

    # Use scene bounds and the first source camera pose (if available) to place
    # static cameras farther away from the center, improving coverage.
    cam_based_static = bounds is not None and src_cams is not None and len(src_cams) > 0
    if cam_based_static:
        bb_min, bb_max, center = bounds
        cam_pos = src_cams[0][:3, 3]
        dir_vec = cam_pos - center  # direction from center to current cam
        if dir_vec.norm() < 1e-4:
            # Degenerate case: fall back to a generic viewing direction
            dir_vec = torch.tensor(
                [0.0, -0.5, -1.0],
                dtype=center.dtype,
                device=center.device,
            )
        radius = dir_vec.norm()
        if radius < 1e-4:
            # fall back to a radius derived from the bbox size
            radius = torch.abs(bb_max - bb_min).max()

        up = torch.tensor(
            [0.0, 1.0, 0.0],
            dtype=center.dtype,
            device=center.device,
        )
    else:
        radius = None
        center = None
        up = None

    # "above" view
    if "above" in render_views:
        if cam_based_static:
            scale_above = 3.0
            above_source = center + scale_above * radius * up / up.norm()
            above_pose = cam_util.lookat_matrix(above_source, center, up)
            scene["cameras"]["above"] = above_pose[None]
        else:
            scene["cameras"]["above"] = top_pose[None]

    # "side" view
    if "side" in render_views:
        if cam_based_static:
            side_dir = torch.linalg.cross(up, dir_vec)
            if side_dir.norm() < 1e-4:
                # If src direction nearly aligns with up, choose an arbitrary side dir
                side_dir = torch.tensor(
                    [1.0, 0.0, 0.0],
                    dtype=center.dtype,
                    device=center.device,
                )
            scale_side = 3.0
            side_source = center + scale_side * radius * side_dir / side_dir.norm()
            side_pose = cam_util.lookat_matrix(side_source, center, up)
            scene["cameras"]["side"] = side_pose[None]
        else:
            scene["cameras"]["side"] = side_pose[None]

    # "front" view
    if "front" in render_views:
        if cam_based_static:
            scale_front = 5.0  # increase this to move the static cam farther away
            front_source = center + scale_front * dir_vec
            front_pose = cam_util.lookat_matrix(front_source, center, up)
            scene["cameras"]["front"] = front_pose[None]
        elif bounds is not None:
            # fallback: same heuristic as original implementation
            bb_min, bb_max, center = bounds
            length = torch.abs(bb_max - bb_min).max()
            front_offset = 1.0
            front_source = center + torch.tensor(
                [0.0, -0.5, -front_offset],
                dtype=center.dtype,
                device=center.device,
            )
            front_target = center
            up = torch.tensor(
                [0.0, 1.0, 0.0],
                dtype=center.dtype,
                device=center.device,
            )
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
                meshes = make_batch_mesh(
                    verts[t][0][None],
                    l_faces[t],
                    colors[t][0][None],
                )
            elif is_right[t] == 1:
                meshes = make_batch_mesh(
                    verts[t][0][None],
                    r_faces[t],
                    colors[t][0][None],
                )
            else:
                meshes = []

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


