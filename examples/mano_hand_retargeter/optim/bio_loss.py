import os

import matplotlib.pyplot as plt
import numpy as np
import torch
import torch.nn.functional as torch_f

SNAP_PARENT = [
    0,  # 0's parent
    0,  # 1's parent
    1,
    2,
    3,
    0,  # 5's parent
    5,
    6,
    7,
    0,  # 9's parent
    9,
    10,
    11,
    0,  # 13's parent
    13,
    14,
    15,
    0,  # 17's parent
    17,
    18,
    19,
]

JOINT_ROOT_IDX = 9

REF_BONE_LINK = (0, 9)  # mid mcp

# bone indexes in 20 bones setting
ID_ROOT_bone = np.array([0, 4, 8, 12, 16])  # ROOT_bone from wrist to MCP
ID_PIP_bone = np.array([1, 5, 9, 13, 17])  # PIP_bone from MCP to PIP
ID_DIP_bone = np.array([2, 6, 10, 14, 18])  # DIP_bone from  PIP to DIP
ID_TIP_bone = np.array([3, 7, 11, 15, 19])  # TIP_bone from DIP to TIP

def plot_hull(theta, hull):
    del_rdp_hull = hull.detach().cpu().numpy()
    theta = theta.detach().cpu().numpy()

    fig = plt.figure()
    figManager = plt.get_current_fig_manager()
    figManager.window.showMaximized()

    ax = fig.add_subplot(111)
    ax.scatter(theta[:, 0], theta[:, 1], s=10, c='r')
    ax.set_xlabel("flexion")
    ax.set_ylabel("abduction")

    plt.plot(del_rdp_hull[:, 0],
             del_rdp_hull[:, 1],
             '-yo', linewidth=2)

    plt.xticks(np.arange(-3, 4, 1))
    plt.yticks(np.arange(-2, 2, 0.5))
    plt.show()


def two_norm(a):
    '''

    Args:
        a: B*M*2 or B*M*3

    Returns:

    '''
    return torch.norm(a, dim=-1)


def one_norm(a):
    '''

    Args:
        a: B*M*2 or B*M*3

    Returns:

    '''
    return torch.norm(a, dim=-1, p=1)


def calculate_joint_angle_loss(thetas, hulls):
    '''

    Args:
        Theta: B*15*2
        hulls: list

    Returns:

    '''

    loss = torch.Tensor([0]).cuda()
    for i in range(15):
        # print("i=",i)
        hull = hulls[i]  # (M*2)
        theta = thetas[:, i]  # (B*2)
        hull = torch.cat((hull, hull[0].unsqueeze(0)), dim=0)

        v = (hull[1:] - hull[:-1]).unsqueeze(0)  # (M-1)*2
        w = - hull[:-1].unsqueeze(0) + theta.unsqueeze(1).repeat(1, hull[:-1].shape[0], 1)  # B*(M-1)*2

        cross_product_2d = w[:, :, 0] * v[:, :, 1] - w[:, :, 1] * v[:, :, 0]
        tmp = torch.sum(cross_product_2d < 1e-6, dim=-1)

        is_outside = (tmp != (hull.shape[0] - 1))
        if not torch.sum(is_outside):
            sub_loss = torch.Tensor([0]).cuda()
        else:
            outside_theta = theta[is_outside]
            outside_theta = outside_theta.unsqueeze(1).repeat(1, hull[:-1].shape[0], 1)
            w_outside = - hull[:-1].unsqueeze(0) + outside_theta  # B*(M-1)*2
            t = torch.clamp(inner_product(w_outside, v) / (two_norm(v) ** 2), min=0, max=1).unsqueeze(2)
            p = hull[:-1] + t * v

            D = one_norm(torch.cos(outside_theta) - torch.cos(p)) + one_norm(torch.sin(outside_theta) - torch.sin(p))
            sub_loss = torch.sum(torch.min(D, dim=-1)[0])

        vis = 0
        if vis:
            print(theta)
            plot_hull(theta, hull)

        loss += sub_loss

    loss /= (15 * thetas.shape[0])

    return loss


def angle_between(v1, v2):
    epsilon = 1e-7
    cos = torch_f.cosine_similarity(v1, v2, dim=-1).clamp(-1 + epsilon, 1 - epsilon)  # (B)
    theta = torch.acos(cos)  # (B)
    return theta


def normalize(vec):
    return torch_f.normalize(vec, p=2, dim=-1)


def inner_product(x1, x2):
    return torch.sum(x1 * x2, dim=-1)


def cross_product(x1, x2):
    return torch.cross(x1, x2, dim=-1)


def axangle2mat_torch(axis, angle, is_normalized=False):
    """ Rotation matrix for rotation angle `angle` around `axis`
    Parameters
    ----------
    axis : [B,M, 3] element sequence
       vector specifying axis for rotation.
    angle :[B,M, ] scalar
       angle of rotation in radians.
    is_normalized : bool, optional
       True if `axis` is already normalized (has norm of 1).  Default False.
    Returns
    -------
    mat : array shape (B, M,3,3)
       rotation matrix for specified rotation
    Notes
    -----
    From: http://en.wikipedia.org/wiki/Rotation_matrix#Axis_and_angle
    """
    B = axis.shape[0]
    M = axis.shape[1]

    if not is_normalized:
        norm_axis = axis.norm(p=2, dim=-1, keepdim=True)
        normed_axis = axis / norm_axis
    else:
        normed_axis = axis
    x, y, z = normed_axis[:, :, 0], normed_axis[:, :, 1], normed_axis[:, :, 2]
    c = torch.cos(angle)
    s = torch.sin(angle)
    C = 1 - c

    xs = x * s;
    ys = y * s;
    zs = z * s  # noqa
    xC = x * C;
    yC = y * C;
    zC = z * C  # noqa
    xyC = x * yC;
    yzC = y * zC;
    zxC = z * xC  # noqa

    TMP = torch.stack([x * xC + c, xyC - zs, zxC + ys, xyC + zs, y * yC + c, yzC - xs, zxC - ys, yzC + xs, z * zC + c],
                      dim=-1)
    return TMP.reshape(B, M, 3, 3)


def interval_loss(value, min, max):
    '''
    calculate interval loss
    Args:
        value: B*M
        max: M
        min: M

    Returns:

    '''

    batch_3d_size = value.shape[0]

    min = min.repeat(value.shape[0], 1)
    max = max.repeat(value.shape[0], 1)

    loss1 = torch.max(min - value, torch.Tensor([0]).cuda())
    loss2 = torch.max(value - max, torch.Tensor([0]).cuda())

    loss = (loss1 + loss2).sum()

    loss /= (batch_3d_size * value.shape[1])

    return loss





class BMCLoss:
    def __init__(
            self,
            lambda_bl=0.,
            lambda_rb=0.,
            lambda_a=0.,
    ):
        self.lambda_bl = lambda_bl
        self.lambda_rb = lambda_rb
        self.lambda_a = lambda_a

        self.lp = os.path.join(os.path.dirname(__file__), "../../_DATA/BMC")
        # resolved_path = os.path.abspath(self.lp)
        # print(f"Resolved path: {resolved_path}")
        # print(f"Current working directory: {os.getcwd()}")
        # exit()

        self.bone_len_max = np.load(os.path.join(self.lp, "bone_len_max.npy"))
        self.bone_len_min = np.load(os.path.join(self.lp, "bone_len_min.npy"))
        self.rb_curvatures_max = np.load(os.path.join(self.lp, "curvatures_max.npy"))
        self.rb_curvatures_min = np.load(os.path.join(self.lp, "curvatures_min.npy"))
        self.rb_PHI_max = np.load(os.path.join(self.lp, "PHI_max.npy"))
        self.rb_PHI_min = np.load(os.path.join(self.lp, "PHI_min.npy"))

        self.joint_angle_limit = np.load(os.path.join(self.lp, "CONVEX_HULLS.npy"),
                                         allow_pickle=True)
        LEN_joint_angle_limit = len(self.joint_angle_limit)

        self.bl_max = torch.from_numpy(self.bone_len_max).float().cuda()
        self.bl_min = torch.from_numpy(self.bone_len_min).float().cuda()
        self.rb_curvatures_max = torch.from_numpy(self.rb_curvatures_max).float().cuda()
        self.rb_curvatures_min = torch.from_numpy(self.rb_curvatures_min).float().cuda()
        self.rb_PHI_max = torch.from_numpy(self.rb_PHI_max).float().cuda()
        self.rb_PHI_min = torch.from_numpy(self.rb_PHI_min).float().cuda()

        self.joint_angle_limit = [torch.from_numpy(self.joint_angle_limit[i]).float().cuda() for i in
                                  range(LEN_joint_angle_limit)]

    def compute_loss(self, ori_joints, valid_mask):
        '''

        Args:
            joints: B*21*3

        Returns:

        '''
        
        joints = ori_joints[valid_mask]
        print(joints.shape, ori_joints.shape)
        batch_size = joints.shape[0]
        final_loss = torch.Tensor([0]).cuda()

        BMC_losses = {"bmc_bl": torch.Tensor([0]).cuda(), "bmc_rb": torch.Tensor([0]).cuda(), "bmc_a": torch.Tensor([0]).cuda()}

        if (self.lambda_bl < 1e-6) and (self.lambda_rb < 1e-6) and (self.lambda_a < 1e-6):
            return final_loss, BMC_losses

        ALL_bones = [
            (
                    joints[:, i, :] -
                    joints[:, SNAP_PARENT[i], :]
            ) for i in range(21)
        ]
        ALL_bones = torch.stack(ALL_bones[1:], dim=1)  # (B,20,3)
        ROOT_bones = ALL_bones[:, ID_ROOT_bone]  # (B,5,3)
        PIP_bones = ALL_bones[:, ID_PIP_bone]
        DIP_bones = ALL_bones[:, ID_DIP_bone]
        TIP_bones = ALL_bones[:, ID_TIP_bone]

        ALL_Z_axis = normalize(ALL_bones)
        PIP_Z_axis = ALL_Z_axis[:, ID_ROOT_bone]
        DIP_Z_axis = ALL_Z_axis[:, ID_PIP_bone]
        TIP_Z_axis = ALL_Z_axis[:, ID_DIP_bone]

        normals = normalize(cross_product(ROOT_bones[:, 1:], ROOT_bones[:, :-1]))

        # compute loss of bone length
        bl_loss = torch.Tensor([0]).cuda()
        if self.lambda_bl:
            bls = two_norm(ALL_bones)  # (B,20,1)
            bl_loss = interval_loss(value=bls, min=self.bl_min, max=self.bl_max)
            final_loss += self.lambda_bl * bl_loss
        BMC_losses["bmc_bl"] = bl_loss

        # compute loss of Root bones
        rb_loss = torch.Tensor([0]).cuda()
        if self.lambda_rb:
            edge_normals = torch.zeros_like(ROOT_bones).cuda()  # (B,5,3)
            edge_normals[:, [0, 4]] = normals[:, [0, 3]]
            edge_normals[:, 1:4] = normalize(normals[:, 1:4] + normals[:, :3])

            curvatures = inner_product(edge_normals[:, 1:] - edge_normals[:, :4],
                                       ROOT_bones[:, 1:] - ROOT_bones[:, :4]) / \
                         (two_norm(ROOT_bones[:, 1:] - ROOT_bones[:, :4]) ** 2)
            PHI = angle_between(ROOT_bones[:, :4], ROOT_bones[:, 1:])  # (B)

            rb_loss = interval_loss(value=curvatures, min=self.rb_curvatures_min, max=self.rb_curvatures_max) + \
                      interval_loss(value=PHI, min=self.rb_PHI_min, max=self.rb_PHI_max)
            final_loss += self.lambda_rb * rb_loss
        BMC_losses["bmc_rb"] = rb_loss

        # compute loss of Joint angles
        a_loss = torch.Tensor([0]).cuda()
        if self.lambda_a:
            # PIP bones
            PIP_X_axis = torch.zeros([batch_size, 5, 3]).cuda()  # (B,5,3)
            PIP_X_axis[:, [0, 1, 4], :] = -normals[:, [0, 1, 3]]
            PIP_X_axis[:, 2:4] = -normalize(normals[:, 2:4] + normals[:, 1:3])  # (B,2,3)
            PIP_Y_axis = normalize(cross_product(PIP_Z_axis, PIP_X_axis))  # (B,5,3)

            PIP_bones_xz = PIP_bones - inner_product(PIP_bones, PIP_Y_axis).unsqueeze(2) * PIP_Y_axis
            PIP_theta_flexion = angle_between(PIP_bones_xz, PIP_Z_axis)  # in global coordinate (B)
            PIP_theta_abduction = angle_between(PIP_bones_xz, PIP_bones)  # in global coordinate (B)
            # x-component of the bone vector
            tmp = inner_product(PIP_bones, PIP_X_axis)
            PIP_theta_flexion = torch.where(tmp < 1e-6, -PIP_theta_flexion, PIP_theta_flexion)
            # y-component of the bone vector
            tmp = torch.sum((PIP_bones * PIP_Y_axis), dim=-1)
            PIP_theta_abduction = torch.where(tmp < 1e-6, -PIP_theta_abduction, PIP_theta_abduction)

            temp_axis = normalize(cross_product(PIP_Z_axis, PIP_bones))
            temp_alpha = angle_between(PIP_Z_axis, PIP_bones)  # alpha belongs to [pi/2, pi]
            temp_R = axangle2mat_torch(axis=temp_axis, angle=temp_alpha, is_normalized=True)

            # DIP bones
            DIP_X_axis = torch.matmul(temp_R, PIP_X_axis.unsqueeze(3)).squeeze()
            DIP_Y_axis = torch.matmul(temp_R, PIP_Y_axis.unsqueeze(3)).squeeze()

            DIP_bones_xz = DIP_bones - inner_product(DIP_bones, DIP_Y_axis).unsqueeze(2) * DIP_Y_axis
            DIP_theta_flexion = angle_between(DIP_bones_xz, DIP_Z_axis)  # in global coordinate
            DIP_theta_abduction = angle_between(DIP_bones_xz, DIP_bones)  # in global coordinate
            # x-component of the bone vector
            tmp = inner_product(DIP_bones, DIP_X_axis)
            DIP_theta_flexion = torch.where(tmp < 0, -DIP_theta_flexion, DIP_theta_flexion)
            # y-component of the bone vector
            tmp = inner_product(DIP_bones, DIP_Y_axis)
            DIP_theta_abduction = torch.where(tmp < 0, -DIP_theta_abduction, DIP_theta_abduction)

            temp_axis = normalize(cross_product(DIP_Z_axis, DIP_bones))
            temp_alpha = angle_between(DIP_Z_axis, DIP_bones)  # alpha belongs to [pi/2, pi]
            temp_R = axangle2mat_torch(axis=temp_axis, angle=temp_alpha, is_normalized=True)

            # TIP bones
            TIP_X_axis = torch.matmul(temp_R, DIP_X_axis.unsqueeze(3)).squeeze()
            TIP_Y_axis = torch.matmul(temp_R, DIP_Y_axis.unsqueeze(3)).squeeze()
            TIP_bones_xz = TIP_bones - inner_product(TIP_bones, TIP_Y_axis).unsqueeze(2) * TIP_Y_axis

            TIP_theta_flexion = angle_between(TIP_bones_xz, TIP_Z_axis)  # in global coordinate
            TIP_theta_abduction = angle_between(TIP_bones_xz, TIP_bones)  # in global coordinate
            # x-component of the bone vector
            tmp = inner_product(TIP_bones, TIP_X_axis)
            TIP_theta_flexion = torch.where(tmp < 1e-6, -TIP_theta_flexion, TIP_theta_flexion)
            # y-component of the bone vector
            tmp = inner_product(TIP_bones, TIP_Y_axis)
            TIP_theta_abduction = torch.where(tmp < 1e-6, -TIP_theta_abduction, TIP_theta_abduction)

            # ALL
            ALL_theta_flexion = torch.cat((PIP_theta_flexion, DIP_theta_flexion, TIP_theta_flexion), dim=-1)
            ALL_theta_abduction = torch.cat((PIP_theta_abduction, DIP_theta_abduction, TIP_theta_abduction), dim=-1)
            ALL_theta = torch.stack((ALL_theta_flexion, ALL_theta_abduction), dim=-1)

            a_loss = calculate_joint_angle_loss(ALL_theta, self.joint_angle_limit)
            final_loss += self.lambda_a * a_loss

        BMC_losses["bmc_a"] = a_loss

        return final_loss, BMC_losses
