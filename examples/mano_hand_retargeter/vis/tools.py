import os
import cv2
import numpy as np
import torch
from PIL import Image


def read_image(path, scale=1):
    im = Image.open(path)
    if scale == 1:
        return np.array(im)
    W, H = im.size
    w, h = int(scale * W), int(scale * H)
    return np.array(im.resize((w, h), Image.ANTIALIAS))


def transform_torch3d(T_c2w):
    """
    :param T_c2w (*, 4, 4)
    returns (*, 3, 3), (*, 3)
    """
    R1 = torch.tensor(
        [[-1.0, 0.0, 0.0], [0.0, -1.0, 0.0], [0.0, 0.0, 1.0],], device=T_c2w.device,
    )
    R2 = torch.tensor(
        [[1.0, 0.0, 0.0], [0.0, -1.0, 0.0], [0.0, 0.0, -1.0],], device=T_c2w.device,
    )
    cam_R, cam_t = T_c2w[..., :3, :3], T_c2w[..., :3, 3]
    cam_R = torch.einsum("...ij,jk->...ik", cam_R, R1)
    cam_t = torch.einsum("ij,...j->...i", R2, cam_t)
    return cam_R, cam_t


def transform_pyrender(T_c2w):
    """
    :param T_c2w (*, 4, 4)
    """
    T_vis = torch.tensor(
        [
            [1.0, 0.0, 0.0, 0.0],
            [0.0, -1.0, 0.0, 0.0],
            [0.0, 0.0, -1.0, 0.0],
            [0.0, 0.0, 0.0, 1.0],
        ],
        device=T_c2w.device,
    )
    return torch.einsum(
        "...ij,jk->...ik", torch.einsum("ij,...jk->...ik", T_vis, T_c2w), T_vis
    )


def mesh_to_geometry(verts, joints, l_faces, r_faces, is_right, vis_mask=None, track_ids=None):
    """
    :param verts (B, T, V, 3)
    :param faces (F, 3)
    :param vis_mask (optional) (B, T) visibility of each person
    :param track_ids (optional) (B,)
    returns list of T verts (B, V, 3), faces (F, 3), colors (B, 3)
    where B is different depending on the visibility of the people
    """
    B, T = verts.shape[:2]
    device = verts.device

    # (B, 3)
    colors = (
        track_to_colors(track_ids)
        if track_ids is not None
        else torch.ones(B, 3, device) * 0.5
    )

    # list T (B, V, 3), T (B, 3), T (F, 3)
    return filter_visible_meshes(verts, joints, colors, l_faces, r_faces, is_right, vis_mask)


def filter_visible_meshes(verts, joints, colors, l_faces, r_faces, is_right, vis_mask=None, vis_opacity=False):
    """
    :param verts (B, T, V, 3)
    :param colors (B, 3)
    :param faces (F, 3)
    :param vis_mask (optional tensor, default None) (B, T) ternary mask
        -1 if not in frame
         0 if temporarily occluded
         1 if visible
    :param vis_opacity (optional bool, default False)
        if True, make occluded people alpha=0.5, otherwise alpha=1
    returns a list of T lists verts (Bi, V, 3), colors (Bi, 4), faces (F, 3)
    """
    # print(verts.shape, joints.shape, colors.shape, l_faces.shape, r_faces.shape, is_right.shape, vis_mask.shape)
    # torch.Size([2, 2, 21, 3]) torch.Size([2, 2, 3, 3]) torch.Size([2, 2, 3]) torch.Size([2, 2]) torch.Size([2, 2])

    #     import ipdb; ipdb.set_trace()
    B, T = verts.shape[:2]
    l_faces = [l_faces for t in range(T)]
    r_faces = [r_faces for t in range(T)]
    if vis_mask is None:
        verts = [verts[:, t] for t in range(T)]
        joints = [joints[:, t] for t in range(T)]
        colors = [colors for t in range(T)]
        is_right = [is_right[:, t] for t in range(T)]
        # print('11111111111', is_right)
        return verts, joints, colors, l_faces, r_faces, is_right, bounds


    # render occluded and visible, but not removed
    vis_mask = vis_mask >= 0
    if vis_opacity:
        alpha = 0.5 * (vis_mask[..., None] + 1)
    else:
        alpha = (vis_mask[..., None] >= 0).float()
    vert_list = [verts[vis_mask[:, t], t] for t in range(T)]
    joints_list = [joints[vis_mask[:, t], t] for t in range(T)]
    is_right_list = [is_right[vis_mask[:, t], t] for t in range(T)]
    colors = [
        torch.cat([colors[vis_mask[:, t]], alpha[vis_mask[:, t], t]], dim=-1)
        for t in range(T)
    ]
    bounds = get_bboxes(verts, vis_mask)
    # print('2222222222222', is_right_list)
    # print('vvvvvv', len(vert_list), vert_list[0].shape)
    # # torch.Size([1, 2, 1, 2]) torch.Size([1, 2, 1, 2])
    # raise ValueError
    return vert_list, joints_list, colors, l_faces, r_faces, is_right_list, bounds


def get_bboxes(verts, vis_mask):
    """
    return bb_min, bb_max, and mean for each track (B, 3) over entire trajectory
    :param verts (B, T, V, 3)
    :param vis_mask (B, T)
    """
    B, T, *_ = verts.shape
    bb_min, bb_max, mean = [], [], []
    for b in range(B):
        v = verts[b, vis_mask[b, :T]]  # (Tb, V, 3)
        bb_min.append(v.amin(dim=(0, 1)))
        bb_max.append(v.amax(dim=(0, 1)))
        mean.append(v.mean(dim=(0, 1)))
    bb_min = torch.stack(bb_min, dim=0)
    bb_max = torch.stack(bb_max, dim=0)
    mean = torch.stack(mean, dim=0)
    # point to a track that's long and close to the camera
    zs = mean[:, 2]
    counts = vis_mask[:, :T].sum(dim=-1)  # (B,)
    mask = counts < 0.8 * T
    zs[mask] = torch.inf
    sel = torch.argmin(zs)
    return bb_min.amin(dim=0), bb_max.amax(dim=0), mean[sel]


def track_to_colors(track_ids):
    """
    :param track_ids (B)
    """
    color_map = torch.from_numpy(get_colors()).to(track_ids)
    return color_map[track_ids] / 255  # (B, 3)


def get_colors():
    #     color_file = os.path.abspath(os.path.join(__file__, "../colors_phalp.txt"))
    color_file = os.path.abspath(os.path.join(__file__, "../colors.txt"))
    RGB_tuples = np.vstack(
        [
            np.loadtxt(color_file, skiprows=0),
            #             np.loadtxt(color_file, skiprows=1),
            np.random.uniform(0, 255, size=(10000, 3)),
            [[0, 0, 0]],
        ]
    )
    b = np.where(RGB_tuples == 0)
    RGB_tuples[b] = 1
    return RGB_tuples.astype(np.float32)


def checkerboard_geometry(
    length=12.0,
    color0=[0.8, 0.9, 0.9],
    color1=[0.6, 0.7, 0.7],
    tile_width=0.5,
    alpha=1.0,
    up="y",
):
    assert up == "y" or up == "z"
    color0 = np.array(color0 + [alpha])
    color1 = np.array(color1 + [alpha])
    radius = length / 2.0
    num_rows = num_cols = int(length / tile_width)
    vertices = []
    vert_colors = []
    faces = []
    face_colors = []
    for i in range(num_rows):
        for j in range(num_cols):
            u0, v0 = j * tile_width - radius, i * tile_width - radius
            us = np.array([u0, u0, u0 + tile_width, u0 + tile_width])
            vs = np.array([v0, v0 + tile_width, v0 + tile_width, v0])
            zs = np.zeros(4)
            if up == "y":
                cur_verts = np.stack([us, zs, vs], axis=-1)  # (4, 3)
            else:
                cur_verts = np.stack([us, vs, zs], axis=-1)  # (4, 3)

            cur_faces = np.array(
                [[0, 1, 3], [1, 2, 3], [0, 3, 1], [1, 3, 2]], dtype=np.int64
            )
            cur_faces += 4 * (i * num_cols + j)  # the number of previously added verts
            use_color0 = (i % 2 == 0 and j % 2 == 0) or (i % 2 == 1 and j % 2 == 1)
            cur_color = color0 if use_color0 else color1
            cur_colors = np.array([cur_color, cur_color, cur_color, cur_color])

            vertices.append(cur_verts)
            faces.append(cur_faces)
            vert_colors.append(cur_colors)
            face_colors.append(cur_colors)

    vertices = np.concatenate(vertices, axis=0).astype(np.float32)
    vert_colors = np.concatenate(vert_colors, axis=0).astype(np.float32)
    faces = np.concatenate(faces, axis=0).astype(np.float32)
    face_colors = np.concatenate(face_colors, axis=0).astype(np.float32)

    return vertices, faces, vert_colors, face_colors


def camera_marker_geometry(radius, height, up):
    assert up == "y" or up == "z"
    if up == "y":
        vertices = np.array(
            [
                [-radius, -radius, 0],
                [radius, -radius, 0],
                [radius, radius, 0],
                [-radius, radius, 0],
                [0, 0, height],
            ]
        )
    else:
        vertices = np.array(
            [
                [-radius, 0, -radius],
                [radius, 0, -radius],
                [radius, 0, radius],
                [-radius, 0, radius],
                [0, -height, 0],
            ]
        )

    faces = np.array(
        [[0, 3, 1], [1, 3, 2], [0, 1, 4], [1, 2, 4], [2, 3, 4], [3, 0, 4],]
    )

    face_colors = np.array(
        [
            [1.0, 1.0, 1.0, 1.0],
            [1.0, 1.0, 1.0, 1.0],
            [0.0, 1.0, 0.0, 1.0],
            [1.0, 0.0, 0.0, 1.0],
            [0.0, 1.0, 0.0, 1.0],
            [1.0, 0.0, 0.0, 1.0],
        ]
    )
    return vertices, faces, face_colors


def vis_keypoints(
    keypts_list,
    img_size,
    radius=6,
    thickness=3,
    kpt_score_thr=0.3,
    dataset="TopDownCocoDataset",
):
    """
    Visualize keypoints
    From ViTPose/mmpose/apis/inference.py
    """
    palette = np.array(
        [
            [255, 128, 0],
            [255, 153, 51],
            [255, 178, 102],
            [230, 230, 0],
            [255, 153, 255],
            [153, 204, 255],
            [255, 102, 255],
            [255, 51, 255],
            [102, 178, 255],
            [51, 153, 255],
            [255, 153, 153],
            [255, 102, 102],
            [255, 51, 51],
            [153, 255, 153],
            [102, 255, 102],
            [51, 255, 51],
            [0, 255, 0],
            [0, 0, 255],
            [255, 0, 0],
            [255, 255, 255],
        ]
    )

    if dataset in (
        "TopDownCocoDataset",
        "BottomUpCocoDataset",
        "TopDownOCHumanDataset",
        "AnimalMacaqueDataset",
    ):
        # show the results
        skeleton = [
            [15, 13],
            [13, 11],
            [16, 14],
            [14, 12],
            [11, 12],
            [5, 11],
            [6, 12],
            [5, 6],
            [5, 7],
            [6, 8],
            [7, 9],
            [8, 10],
            [1, 2],
            [0, 1],
            [0, 2],
            [1, 3],
            [2, 4],
            [3, 5],
            [4, 6],
        ]

        pose_link_color = palette[
            [0, 0, 0, 0, 7, 7, 7, 9, 9, 9, 9, 9, 16, 16, 16, 16, 16, 16, 16]
        ]
        pose_kpt_color = palette[
            [16, 16, 16, 16, 16, 9, 9, 9, 9, 9, 9, 0, 0, 0, 0, 0, 0]
        ]

    elif dataset == "TopDownCocoWholeBodyDataset":
        # show the results
        skeleton = [
            [15, 13],
            [13, 11],
            [16, 14],
            [14, 12],
            [11, 12],
            [5, 11],
            [6, 12],
            [5, 6],
            [5, 7],
            [6, 8],
            [7, 9],
            [8, 10],
            [1, 2],
            [0, 1],
            [0, 2],
            [1, 3],
            [2, 4],
            [3, 5],
            [4, 6],
            [15, 17],
            [15, 18],
            [15, 19],
            [16, 20],
            [16, 21],
            [16, 22],
            [91, 92],
            [92, 93],
            [93, 94],
            [94, 95],
            [91, 96],
            [96, 97],
            [97, 98],
            [98, 99],
            [91, 100],
            [100, 101],
            [101, 102],
            [102, 103],
            [91, 104],
            [104, 105],
            [105, 106],
            [106, 107],
            [91, 108],
            [108, 109],
            [109, 110],
            [110, 111],
            [112, 113],
            [113, 114],
            [114, 115],
            [115, 116],
            [112, 117],
            [117, 118],
            [118, 119],
            [119, 120],
            [112, 121],
            [121, 122],
            [122, 123],
            [123, 124],
            [112, 125],
            [125, 126],
            [126, 127],
            [127, 128],
            [112, 129],
            [129, 130],
            [130, 131],
            [131, 132],
        ]

        pose_link_color = palette[
            [0, 0, 0, 0, 7, 7, 7, 9, 9, 9, 9, 9, 16, 16, 16, 16, 16, 16, 16]
            + [16, 16, 16, 16, 16, 16]
            + [0, 0, 0, 0, 4, 4, 4, 4, 8, 8, 8, 8, 12, 12, 12, 12, 16, 16, 16, 16]
            + [0, 0, 0, 0, 4, 4, 4, 4, 8, 8, 8, 8, 12, 12, 12, 12, 16, 16, 16, 16]
        ]
        pose_kpt_color = palette[
            [16, 16, 16, 16, 16, 9, 9, 9, 9, 9, 9, 0, 0, 0, 0, 0, 0]
            + [0, 0, 0, 0, 0, 0]
            + [19] * (68 + 42)
        ]

    elif dataset == "TopDownAicDataset":
        skeleton = [
            [2, 1],
            [1, 0],
            [0, 13],
            [13, 3],
            [3, 4],
            [4, 5],
            [8, 7],
            [7, 6],
            [6, 9],
            [9, 10],
            [10, 11],
            [12, 13],
            [0, 6],
            [3, 9],
        ]

        pose_link_color = palette[[9, 9, 9, 9, 9, 9, 16, 16, 16, 16, 16, 0, 7, 7]]
        pose_kpt_color = palette[[9, 9, 9, 9, 9, 9, 16, 16, 16, 16, 16, 16, 0, 0]]

    elif dataset == "TopDownMpiiDataset":
        skeleton = [
            [0, 1],
            [1, 2],
            [2, 6],
            [6, 3],
            [3, 4],
            [4, 5],
            [6, 7],
            [7, 8],
            [8, 9],
            [8, 12],
            [12, 11],
            [11, 10],
            [8, 13],
            [13, 14],
            [14, 15],
        ]

        pose_link_color = palette[[16, 16, 16, 16, 16, 16, 7, 7, 0, 9, 9, 9, 9, 9, 9]]
        pose_kpt_color = palette[[16, 16, 16, 16, 16, 16, 7, 7, 0, 0, 9, 9, 9, 9, 9, 9]]

    elif dataset == "TopDownMpiiTrbDataset":
        skeleton = [
            [12, 13],
            [13, 0],
            [13, 1],
            [0, 2],
            [1, 3],
            [2, 4],
            [3, 5],
            [0, 6],
            [1, 7],
            [6, 7],
            [6, 8],
            [7, 9],
            [8, 10],
            [9, 11],
            [14, 15],
            [16, 17],
            [18, 19],
            [20, 21],
            [22, 23],
            [24, 25],
            [26, 27],
            [28, 29],
            [30, 31],
            [32, 33],
            [34, 35],
            [36, 37],
            [38, 39],
        ]

        pose_link_color = palette[[16] * 14 + [19] * 13]
        pose_kpt_color = palette[[16] * 14 + [0] * 26]

    elif dataset in ("OneHand10KDataset", "FreiHandDataset", "PanopticDataset"):
        skeleton = [
            [0, 1],
            [1, 2],
            [2, 3],
            [3, 4],
            [0, 5],
            [5, 6],
            [6, 7],
            [7, 8],
            [0, 9],
            [9, 10],
            [10, 11],
            [11, 12],
            [0, 13],
            [13, 14],
            [14, 15],
            [15, 16],
            [0, 17],
            [17, 18],
            [18, 19],
            [19, 20],
        ]

        pose_link_color = palette[
            [0, 0, 0, 0, 4, 4, 4, 4, 8, 8, 8, 8, 12, 12, 12, 12, 16, 16, 16, 16]
        ]
        pose_kpt_color = palette[
            [0, 0, 0, 0, 0, 4, 4, 4, 4, 8, 8, 8, 8, 12, 12, 12, 12, 16, 16, 16, 16]
        ]

    elif dataset == "InterHand2DDataset":
        skeleton = [
            [0, 1],
            [1, 2],
            [2, 3],
            [4, 5],
            [5, 6],
            [6, 7],
            [8, 9],
            [9, 10],
            [10, 11],
            [12, 13],
            [13, 14],
            [14, 15],
            [16, 17],
            [17, 18],
            [18, 19],
            [3, 20],
            [7, 20],
            [11, 20],
            [15, 20],
            [19, 20],
        ]

        pose_link_color = palette[
            [0, 0, 0, 4, 4, 4, 8, 8, 8, 12, 12, 12, 16, 16, 16, 0, 4, 8, 12, 16]
        ]
        pose_kpt_color = palette[
            [0, 0, 0, 0, 4, 4, 4, 4, 8, 8, 8, 8, 12, 12, 12, 12, 16, 16, 16, 16, 0]
        ]

    elif dataset == "Face300WDataset":
        # show the results
        skeleton = []

        pose_link_color = palette[[]]
        pose_kpt_color = palette[[19] * 68]
        kpt_score_thr = 0

    elif dataset == "FaceAFLWDataset":
        # show the results
        skeleton = []

        pose_link_color = palette[[]]
        pose_kpt_color = palette[[19] * 19]
        kpt_score_thr = 0

    elif dataset == "FaceCOFWDataset":
        # show the results
        skeleton = []

        pose_link_color = palette[[]]
        pose_kpt_color = palette[[19] * 29]
        kpt_score_thr = 0

    elif dataset == "FaceWFLWDataset":
        # show the results
        skeleton = []

        pose_link_color = palette[[]]
        pose_kpt_color = palette[[19] * 98]
        kpt_score_thr = 0

    elif dataset == "AnimalHorse10Dataset":
        skeleton = [
            [0, 1],
            [1, 12],
            [12, 16],
            [16, 21],
            [21, 17],
            [17, 11],
            [11, 10],
            [10, 8],
            [8, 9],
            [9, 12],
            [2, 3],
            [3, 4],
            [5, 6],
            [6, 7],
            [13, 14],
            [14, 15],
            [18, 19],
            [19, 20],
        ]

        pose_link_color = palette[[4] * 10 + [6] * 2 + [6] * 2 + [7] * 2 + [7] * 2]
        pose_kpt_color = palette[
            [4, 4, 6, 6, 6, 6, 6, 6, 4, 4, 4, 4, 4, 7, 7, 7, 4, 4, 7, 7, 7, 4]
        ]

    elif dataset == "AnimalFlyDataset":
        skeleton = [
            [1, 0],
            [2, 0],
            [3, 0],
            [4, 3],
            [5, 4],
            [7, 6],
            [8, 7],
            [9, 8],
            [11, 10],
            [12, 11],
            [13, 12],
            [15, 14],
            [16, 15],
            [17, 16],
            [19, 18],
            [20, 19],
            [21, 20],
            [23, 22],
            [24, 23],
            [25, 24],
            [27, 26],
            [28, 27],
            [29, 28],
            [30, 3],
            [31, 3],
        ]

        pose_link_color = palette[[0] * 25]
        pose_kpt_color = palette[[0] * 32]

    elif dataset == "AnimalLocustDataset":
        skeleton = [
            [1, 0],
            [2, 1],
            [3, 2],
            [4, 3],
            [6, 5],
            [7, 6],
            [9, 8],
            [10, 9],
            [11, 10],
            [13, 12],
            [14, 13],
            [15, 14],
            [17, 16],
            [18, 17],
            [19, 18],
            [21, 20],
            [22, 21],
            [24, 23],
            [25, 24],
            [26, 25],
            [28, 27],
            [29, 28],
            [30, 29],
            [32, 31],
            [33, 32],
            [34, 33],
        ]

        pose_link_color = palette[[0] * 26]
        pose_kpt_color = palette[[0] * 35]

    elif dataset == "AnimalZebraDataset":
        skeleton = [[1, 0], [2, 1], [3, 2], [4, 2], [5, 7], [6, 7], [7, 2], [8, 7]]

        pose_link_color = palette[[0] * 8]
        pose_kpt_color = palette[[0] * 9]

    elif dataset in "AnimalPoseDataset":
        skeleton = [
            [0, 1],
            [0, 2],
            [1, 3],
            [0, 4],
            [1, 4],
            [4, 5],
            [5, 7],
            [6, 7],
            [5, 8],
            [8, 12],
            [12, 16],
            [5, 9],
            [9, 13],
            [13, 17],
            [6, 10],
            [10, 14],
            [14, 18],
            [6, 11],
            [11, 15],
            [15, 19],
        ]

        pose_link_color = palette[[0] * 20]
        pose_kpt_color = palette[[0] * 20]
    else:
        NotImplementedError()

    img_w, img_h = img_size
    img = 255 * np.ones((img_h, img_w, 3), dtype=np.uint8)
    img = imshow_keypoints(
        img,
        keypts_list,
        skeleton,
        kpt_score_thr,
        pose_kpt_color,
        pose_link_color,
        radius,
        thickness,
    )
    alpha = 255 * (img != 255).any(axis=-1, keepdims=True).astype(np.uint8)
    return np.concatenate([img, alpha], axis=-1)


def imshow_keypoints(
    img,
    pose_result,
    skeleton=None,
    kpt_score_thr=0.3,
    pose_kpt_color=None,
    pose_link_color=None,
    radius=4,
    thickness=1,
    show_keypoint_weight=False,
):
    """Draw keypoints and links on an image.
    From ViTPose/mmpose/core/visualization/image.py

    Args:
        img (H, W, 3) array
        pose_result (list[kpts]): The poses to draw. Each element kpts is
            a set of K keypoints as an Kx3 numpy.ndarray, where each
            keypoint is represented as x, y, score.
        kpt_score_thr (float, optional): Minimum score of keypoints
            to be shown. Default: 0.3.
        pose_kpt_color (np.array[Nx3]`): Color of N keypoints. If None,
            the keypoint will not be drawn.
        pose_link_color (np.array[Mx3]): Color of M links. If None, the
            links will not be drawn.
        thickness (int): Thickness of lines.
        show_keypoint_weight (bool): If True, opacity indicates keypoint score
    """
    img_h, img_w, _ = img.shape
    idcs = [0, 16, 15, 18, 17, 5, 2, 6, 3, 7, 4, 12, 9, 13, 10, 14, 11]
    for kpts in pose_result:
        kpts = np.array(kpts, copy=False)[idcs]

        # draw each point on image
        if pose_kpt_color is not None:
            assert len(pose_kpt_color) == len(kpts)
            for kid, kpt in enumerate(kpts):
                x_coord, y_coord, kpt_score = int(kpt[0]), int(kpt[1]), kpt[2]
                if kpt_score > kpt_score_thr:
                    color = tuple(int(c) for c in pose_kpt_color[kid])
                    if show_keypoint_weight:
                        img_copy = img.copy()
                        cv2.circle(
                            img_copy, (int(x_coord), int(y_coord)), radius, color, -1
                        )
                        transparency = max(0, min(1, kpt_score))
                        cv2.addWeighted(
                            img_copy, transparency, img, 1 - transparency, 0, dst=img
                        )
                    else:
                        cv2.circle(img, (int(x_coord), int(y_coord)), radius, color, -1)

        # draw links
        if skeleton is not None and pose_link_color is not None:
            assert len(pose_link_color) == len(skeleton)
            for sk_id, sk in enumerate(skeleton):
                pos1 = (int(kpts[sk[0], 0]), int(kpts[sk[0], 1]))
                pos2 = (int(kpts[sk[1], 0]), int(kpts[sk[1], 1]))
                if (
                    pos1[0] > 0
                    and pos1[0] < img_w
                    and pos1[1] > 0
                    and pos1[1] < img_h
                    and pos2[0] > 0
                    and pos2[0] < img_w
                    and pos2[1] > 0
                    and pos2[1] < img_h
                    and kpts[sk[0], 2] > kpt_score_thr
                    and kpts[sk[1], 2] > kpt_score_thr
                ):
                    color = tuple(int(c) for c in pose_link_color[sk_id])
                    if show_keypoint_weight:
                        img_copy = img.copy()
                        X = (pos1[0], pos2[0])
                        Y = (pos1[1], pos2[1])
                        mX = np.mean(X)
                        mY = np.mean(Y)
                        length = ((Y[0] - Y[1]) ** 2 + (X[0] - X[1]) ** 2) ** 0.5
                        angle = math.degrees(math.atan2(Y[0] - Y[1], X[0] - X[1]))
                        stickwidth = 2
                        polygon = cv2.ellipse2Poly(
                            (int(mX), int(mY)),
                            (int(length / 2), int(stickwidth)),
                            int(angle),
                            0,
                            360,
                            1,
                        )
                        cv2.fillConvexPoly(img_copy, polygon, color)
                        transparency = max(
                            0, min(1, 0.5 * (kpts[sk[0], 2] + kpts[sk[1], 2]))
                        )
                        cv2.addWeighted(
                            img_copy, transparency, img, 1 - transparency, 0, dst=img
                        )
                    else:
                        cv2.line(img, pos1, pos2, color, thickness=thickness)

    return img


#############################
# temporal optimization
#############################
def quaternion_to_angle_axis(quaternion: torch.Tensor) -> torch.Tensor:
    """
    This function is borrowed from https://github.com/kornia/kornia

    Convert quaternion vector to angle axis of rotation.

    Adapted from ceres C++ library: ceres-solver/include/ceres/rotation.h

    Args:
        quaternion (torch.Tensor): tensor with quaternions.

    Return:
        torch.Tensor: tensor with angle axis of rotation.

    Shape:
        - Input: :math:`(*, 4)` where `*` means, any number of dimensions
        - Output: :math:`(*, 3)`

    Example:
        >>> quaternion = torch.rand(2, 4)  # Nx4
        >>> angle_axis = tgm.quaternion_to_angle_axis(quaternion)  # Nx3
    """
    if not torch.is_tensor(quaternion):
        raise TypeError("Input type is not a torch.Tensor. Got {}".format(
            type(quaternion)))

    if not quaternion.shape[-1] == 4:
        raise ValueError("Input must be a tensor of shape Nx4 or 4. Got {}"
                         .format(quaternion.shape))
    # unpack input and compute conversion
    q1: torch.Tensor = quaternion[..., 1]
    q2: torch.Tensor = quaternion[..., 2]
    q3: torch.Tensor = quaternion[..., 3]
    sin_squared_theta: torch.Tensor = q1 * q1 + q2 * q2 + q3 * q3

    sin_theta: torch.Tensor = torch.sqrt(sin_squared_theta)
    cos_theta: torch.Tensor = quaternion[..., 0]
    two_theta: torch.Tensor = 2.0 * torch.where(
        cos_theta < 0.0,
        torch.atan2(-sin_theta, -cos_theta),
        torch.atan2(sin_theta, cos_theta))

    k_pos: torch.Tensor = two_theta / sin_theta
    k_neg: torch.Tensor = 2.0 * torch.ones_like(sin_theta)
    k: torch.Tensor = torch.where(sin_squared_theta > 0.0, k_pos, k_neg)

    angle_axis: torch.Tensor = torch.zeros_like(quaternion)[..., :3]
    angle_axis[..., 0] += q1 * k
    angle_axis[..., 1] += q2 * k
    angle_axis[..., 2] += q3 * k
    return angle_axis

def rotation_matrix_to_quaternion(rotation_matrix, eps=1e-6):
    """
    This function is borrowed from https://github.com/kornia/kornia

    Convert 3x4 rotation matrix to 4d quaternion vector

    This algorithm is based on algorithm described in
    https://github.com/KieranWynn/pyquaternion/blob/master/pyquaternion/quaternion.py#L201

    Args:
        rotation_matrix (Tensor): the rotation matrix to convert.

    Return:
        Tensor: the rotation in quaternion

    Shape:
        - Input: :math:`(N, 3, 4)`
        - Output: :math:`(N, 4)`

    Example:
        >>> input = torch.rand(4, 3, 4)  # Nx3x4
        >>> output = tgm.rotation_matrix_to_quaternion(input)  # Nx4
    """
    if not torch.is_tensor(rotation_matrix):
        raise TypeError("Input type is not a torch.Tensor. Got {}".format(
            type(rotation_matrix)))

    if len(rotation_matrix.shape) > 3:
        raise ValueError(
            "Input size must be a three dimensional tensor. Got {}".format(
                rotation_matrix.shape))
    if not rotation_matrix.shape[-2:] == (3, 4):
        raise ValueError(
            "Input size must be a N x 3 x 4  tensor. Got {}".format(
                rotation_matrix.shape))

    rmat_t = torch.transpose(rotation_matrix, 1, 2)

    mask_d2 = rmat_t[:, 2, 2] < eps

    mask_d0_d1 = rmat_t[:, 0, 0] > rmat_t[:, 1, 1]
    mask_d0_nd1 = rmat_t[:, 0, 0] < -rmat_t[:, 1, 1]

    t0 = 1 + rmat_t[:, 0, 0] - rmat_t[:, 1, 1] - rmat_t[:, 2, 2]
    q0 = torch.stack([rmat_t[:, 1, 2] - rmat_t[:, 2, 1],
                      t0, rmat_t[:, 0, 1] + rmat_t[:, 1, 0],
                      rmat_t[:, 2, 0] + rmat_t[:, 0, 2]], -1)
    t0_rep = t0.repeat(4, 1).t()

    t1 = 1 - rmat_t[:, 0, 0] + rmat_t[:, 1, 1] - rmat_t[:, 2, 2]
    q1 = torch.stack([rmat_t[:, 2, 0] - rmat_t[:, 0, 2],
                      rmat_t[:, 0, 1] + rmat_t[:, 1, 0],
                      t1, rmat_t[:, 1, 2] + rmat_t[:, 2, 1]], -1)
    t1_rep = t1.repeat(4, 1).t()

    t2 = 1 - rmat_t[:, 0, 0] - rmat_t[:, 1, 1] + rmat_t[:, 2, 2]
    q2 = torch.stack([rmat_t[:, 0, 1] - rmat_t[:, 1, 0],
                      rmat_t[:, 2, 0] + rmat_t[:, 0, 2],
                      rmat_t[:, 1, 2] + rmat_t[:, 2, 1], t2], -1)
    t2_rep = t2.repeat(4, 1).t()

    t3 = 1 + rmat_t[:, 0, 0] + rmat_t[:, 1, 1] + rmat_t[:, 2, 2]
    q3 = torch.stack([t3, rmat_t[:, 1, 2] - rmat_t[:, 2, 1],
                      rmat_t[:, 2, 0] - rmat_t[:, 0, 2],
                      rmat_t[:, 0, 1] - rmat_t[:, 1, 0]], -1)
    t3_rep = t3.repeat(4, 1).t()

    mask_c0 = mask_d2 * mask_d0_d1
    mask_c1 = mask_d2 * ~mask_d0_d1
    mask_c2 = ~mask_d2 * mask_d0_nd1
    mask_c3 = ~mask_d2 * ~mask_d0_nd1
    mask_c0 = mask_c0.view(-1, 1).type_as(q0)
    mask_c1 = mask_c1.view(-1, 1).type_as(q1)
    mask_c2 = mask_c2.view(-1, 1).type_as(q2)
    mask_c3 = mask_c3.view(-1, 1).type_as(q3)

    q = q0 * mask_c0 + q1 * mask_c1 + q2 * mask_c2 + q3 * mask_c3
    q /= torch.sqrt(t0_rep * mask_c0 + t1_rep * mask_c1 +  # noqa
                    t2_rep * mask_c2 + t3_rep * mask_c3)  # noqa
    q *= 0.5
    return q

def rotation_matrix_to_angle_axis(rotation_matrix):
    """
    Convert 3x4 rotation matrix to Rodrigues vector
    Args:
        rotation_matrix (Tensor): rotation matrix.
    Returns:
        Tensor: Rodrigues vector transformation.
    Shape:
        - Input: :math:`(N, 3, 4)`
        - Output: :math:`(N, 3)`
    Example:
        >>> input = torch.rand(2, 3, 4)  # Nx4x4
        >>> output = tgm.rotation_matrix_to_angle_axis(input)  # Nx3
    """
    if rotation_matrix.shape[1:] == (3,3):
        hom_mat = torch.tensor([0, 0, 1]).float()
        rot_mat = rotation_matrix.reshape(-1, 3, 3)
        batch_size, device = rot_mat.shape[0], rot_mat.device
        hom_mat = hom_mat.view(1, 3, 1)
        hom_mat = hom_mat.repeat(batch_size, 1, 1).contiguous()
        hom_mat = hom_mat.to(device)
        rotation_matrix = torch.cat([rot_mat, hom_mat], dim=-1)

    quaternion = rotation_matrix_to_quaternion(rotation_matrix)
    aa = quaternion_to_angle_axis(quaternion)
    aa[torch.isnan(aa)] = 0.0
    return aa

def quat2mat(quat):
    """Convert quaternion coefficients to rotation matrix.
    把四元组的系数转化成旋转矩阵。四元组表示三维旋转
    Args:
        quat: size = [B, 4] 4 <===>(w, x, y, z)
    Returns:
        Rotation matrix corresponding to the quaternion -- size = [B, 3, 3]
    """
    norm_quat = quat
    norm_quat = norm_quat/norm_quat.norm(p=2, dim=1, keepdim=True)
    w, x, y, z = norm_quat[:,0], norm_quat[:,1], norm_quat[:,2], norm_quat[:,3]

    B = quat.size(0)

    w2, x2, y2, z2 = w.pow(2), x.pow(2), y.pow(2), z.pow(2)
    wx, wy, wz = w*x, w*y, w*z
    xy, xz, yz = x*y, x*z, y*z

    rotMat = torch.stack([w2 + x2 - y2 - z2, 2*xy - 2*wz, 2*wy + 2*xz,
                          2*wz + 2*xy, w2 - x2 + y2 - z2, 2*yz - 2*wx,
                          2*xz - 2*wy, 2*wx + 2*yz, w2 - x2 - y2 + z2], dim=1).view(B, 3, 3)
    return rotMat

def batch_rodrigues(param):
    #param N x 3
    batch_size = param.shape[0]
    #沿第二维（3个数）进行求二次范数：||x||，下面就是进行标准化，每三个数除以他们的范数。
    l1norm = torch.norm(param + 1e-8, p = 2, dim = 1)
    angle = torch.unsqueeze(l1norm, -1)
    normalized = torch.div(param, angle)
    angle = angle * 0.5
    #上面算出的是一个向量的长度：sqrt(x**2+y**2+z**2)/2,所以这个长度的的cos
    v_cos = torch.cos(angle)
    v_sin = torch.sin(angle)
    #用四元组表示三维旋转，有时间看一下×××××××××
    quat = torch.cat([v_cos, v_sin * normalized], dim = 1)

    return quat2mat(quat)

def smooth_global_rot_matrix(pred_rots, OE_filter):
    rot_mat = batch_rodrigues(pred_rots[None]).squeeze(0)
    smoothed_rot_mat = OE_filter.process(rot_mat)
    smoothed_rot = rotation_matrix_to_angle_axis(smoothed_rot_mat.reshape(1,3,3)).reshape(-1)
    return smoothed_rot

def create_OneEuroFilter(smooth_coeff):
    return {'poses': OneEuroFilter(smooth_coeff, 0.7), 'cam': OneEuroFilter(1.6, 0.7), 'betas': OneEuroFilter(0.6, 0.7), 'global_orient': OneEuroFilter(smooth_coeff, 0.7)}

def smooth_results(global_orientation, body_pose, body_shape, is_right, cam=None):
    filters = {}
    filters[0] = create_OneEuroFilter(smooth_coeff=1)
    filters[1] = create_OneEuroFilter(smooth_coeff=1)
    # print(global_orientation.shape, body_pose.shape, body_shape.shape, is_right.shape, cam.shape)

    for idx in range(len(global_orientation)):
        for time in range(len(global_orientation[0])):
            # print('!!!!!!!!! running temporal smooth')
            handedness = int(is_right[idx, time])
            global_orientation[idx, time] = smooth_global_rot_matrix(global_orientation[idx, time], filters[handedness]['global_orient'])
            body_pose[idx, time] = filters[handedness]['poses'].process(body_pose[idx, time].reshape(45)).reshape(15, 3)
            if cam is not None:
                cam[idx, time] = filters[handedness]['cam'].process(cam[idx, time])

    return global_orientation, body_pose, body_shape, cam

'''
learn from the minimal hand https://github.com/CalciferZh/minimal-hand
'''
class LowPassFilter:
  def __init__(self):
    self.prev_raw_value = None
    self.prev_filtered_value = None

  def process(self, value, alpha):
    if self.prev_raw_value is None:
        s = value
    else:
        s = alpha * value + (1.0 - alpha) * self.prev_filtered_value
    self.prev_raw_value = value
    self.prev_filtered_value = s
    return s

class OneEuroFilter:
  def __init__(self, mincutoff=1.0, beta=0.0, dcutoff=1.0, freq=30):
    # min_cutoff: Decreasing the minimum cutoff frequency decreases slow speed jitter
    # beta: Increasing the speed coefficient(beta) decreases speed lag.
    self.freq = freq
    self.mincutoff = mincutoff
    self.beta = beta
    self.dcutoff = dcutoff
    self.x_filter = LowPassFilter()
    self.dx_filter = LowPassFilter()

  def compute_alpha(self, cutoff):
    te = 1.0 / self.freq
    tau = 1.0 / (2 * np.pi * cutoff)
    return 1.0 / (1.0 + tau / te)

  def process(self, x, print_inter=False):
    prev_x = self.x_filter.prev_raw_value
    dx = 0.0 if prev_x is None else (x - prev_x) * self.freq
    edx = self.dx_filter.process(dx, self.compute_alpha(self.dcutoff))
    
    if isinstance(edx, float):
        cutoff = self.mincutoff + self.beta * np.abs(edx)
    elif isinstance(edx, np.ndarray):
        cutoff = self.mincutoff + self.beta * np.abs(edx)
    elif isinstance(edx, torch.Tensor):
        cutoff = self.mincutoff + self.beta * torch.abs(edx)
    if print_inter:
        print(self.compute_alpha(cutoff))
    return self.x_filter.process(x, self.compute_alpha(cutoff))