import os
import numpy as np
import trimesh


def get_mesh_bb(mesh):
    """
    :param mesh - trimesh mesh object
    returns bb_min (3), bb_max (3)
    """
    bb_min = mesh.vertices.max(axis=0)
    bb_max = mesh.vertices.min(axis=0)
    return bb_min, bb_max


def get_scene_bb(meshes):
    """
    :param mesh_seqs - (potentially nested) list of trimesh objects
    returns bb_min (3), bb_max (3)
    """
    if isinstance(meshes, trimesh.Trimesh):
        return get_mesh_bb(meshes)

    bb_mins, bb_maxs = zip(*[get_scene_bb(mesh) for mesh in meshes])
    bb_mins = np.stack(bb_mins, axis=0)
    bb_maxs = np.stack(bb_maxs, axis=0)
    return bb_mins.min(axis=0), bb_maxs.max(axis=0)


def make_batch_mesh(verts, faces, colors):
    """
    convenience function to make batch of meshes
    meshs have same faces in batch, verts have same color in mesh
    :param verts (B, V, 3)
    :param faces (F, 3)
    :param colors (B, 3)
    """
    B, V, _ = verts.shape
    return [make_mesh(verts[b], faces, colors[b, None].expand(V, -1)) for b in range(B)]


def make_mesh(verts, faces, colors=None, yup=True):
    """
    create a trimesh object for the faces and vertices
    :param verts (V, 3) tensor
    :param faces (F, 3) tensor
    :param colors (optional) (V, 3) tensor
    :param yup (optional bool) whether or not to save with Y up
    """
    verts = verts.detach().cpu().numpy()
    faces = faces.detach().cpu().numpy()
    if yup:
        verts = np.array([1, -1, -1])[None, :] * verts
    if colors is None:
        colors = np.ones_like(verts) * 0.5
    else:
        colors = colors.detach().cpu().numpy()
    return trimesh.Trimesh(
        vertices=verts, faces=faces, vertex_colors=colors, process=False
    )


def save_mesh_scenes(out_dir, scenes):
    """
    :param scenes, list of scenes (list of meshes)
    """
    assert isinstance(scenes, list)
    assert isinstance(scenes[0], list)
    B = len(scenes[0])
    if B == 1:
        save_meshes_to_obj(out_dir, [x[0] for x in scenes])
    else:
        save_scenes_to_glb(out_dir, scenes)


def save_scenes_to_glb(out_dir, scenes):
    """
    Saves a list of scenes (list of meshes) each to glb files
    """
    os.makedirs(out_dir, exist_ok=True)
    for t, meshes in enumerate(scenes):
        save_meshes_to_glb(f"{out_dir}/scene_{t:03d}.glb", meshes)


def save_meshes_to_glb(path, meshes, names=None):
    """
    put trimesh meshes in a scene and export to glb
    """
    if names is not None:
        assert len(meshes) == len(names)

    scene = trimesh.Scene()
    for i, mesh in enumerate(meshes):
        name = f"mesh_{i:03d}" if names is None else names[i]
        scene.add_geometry(mesh, node_name=name)

    with open(path, "wb") as f:
        f.write(trimesh.exchange.gltf.export_glb(scene, include_normals=True))


def save_meshes_to_obj(out_dir, meshes, names=None):
    if names is not None:
        assert len(meshes) == len(names)

    os.makedirs(out_dir, exist_ok=True)
    for i, mesh in enumerate(meshes):
        name = f"mesh_{i:03d}" if names is None else names[i]
        path = os.path.join(out_dir, f"{name}.obj")
        with open(path, "w") as f:
            mesh.export(f, file_type="obj", include_color=False, include_normals=True)

def vertices_to_trimesh(vertices, faces, mesh_base_color=(1.0, 1.0, 0.9), 
                        rot_axis=[1,0,0], rot_angle=0, is_right=1):
    # material = pyrender.MetallicRoughnessMaterial(
    #     metallicFactor=0.0,
    #     alphaMode='OPAQUE',
    #     baseColorFactor=(*mesh_base_color, 1.0))
    faces_new = np.array([[92, 38, 234],
                            [234, 38, 239],
                            [38, 122, 239],
                            [239, 122, 279],
                            [122, 118, 279],
                            [279, 118, 215],
                            [118, 117, 215],
                            [215, 117, 214],
                            [117, 119, 214],
                            [214, 119, 121],
                            [119, 120, 121],
                            [121, 120, 78],
                            [120, 108, 78],
                            [78, 108, 79]])
    faces = np.concatenate([faces, faces_new], axis=0)
    vertex_colors = np.array([(*mesh_base_color, 1.0)] * vertices.shape[0])
    # print(vertices.shape, self.faces.shape)
    mesh = trimesh.Trimesh(vertices.copy(), faces.copy(), vertex_colors=vertex_colors)
    # mesh = trimesh.Trimesh(vertices.copy(), self.faces.copy())
    
    rot = trimesh.transformations.rotation_matrix(
            np.radians(rot_angle), rot_axis)
    mesh.apply_transform(rot)

    rot = trimesh.transformations.rotation_matrix(
        np.radians(180), [1, 0, 0])
    mesh.apply_transform(rot)
    return mesh
