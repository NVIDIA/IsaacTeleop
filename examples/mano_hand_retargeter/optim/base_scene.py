import os
import numpy as np

import torch
import torch.nn as nn
import torch.nn.functional as F

from body_model import MANO_JOINTS, run_mano
from geometry.rotation import (
    rotation_matrix_to_angle_axis,
    angle_axis_to_rotation_matrix,
)
from util.logger import Logger
from util.tensor import move_to, detach_all

# from .helpers import estimate_initial_trans
from .params import CameraParams

J_HAND = len(MANO_JOINTS) - 1  # no root


class BaseSceneModel(nn.Module):
    """
    Scene model of sequences of human poses.
    All poses are in their own INDEPENDENT camera reference frames.
    A basic class mostly for testing purposes.

    Parameters:
        batch_size:  number of sequences to optimize
        seq_len:     length of the sequences
        body_model:  MANO hand model
        pose_prior:  VPoser model
        fit_gender:  gender of model (optional)
    """

    def __init__(
        self,
        batch_size,
        seq_len,
        body_model,
        pose_prior,
        # fit_gender="neutral",
        use_init=False,
        opt_cams=False,
        opt_scale=True,
        **kwargs,
    ):
        super().__init__()
        B, T = batch_size, seq_len
        self.batch_size = batch_size
        self.seq_len = seq_len

        self.body_model = body_model
        self.hand_mean = self.body_model.hand_mean

        self.pose_prior = pose_prior
        if self.pose_prior is not None:
            self.latent_pose_dim = self.pose_prior.latentD

        self.num_betas = body_model.num_betas

        self.use_init = use_init
        print("USE INIT", use_init)
        self.opt_scale = opt_scale
        self.opt_cams = opt_cams
        print("OPT SCALE", self.opt_scale)
        print("OPT CAMERAS", self.opt_cams)
        print("Batch size: ", batch_size)
        self.params = CameraParams(batch_size)

    def initialize(self, obs_data, cam_data):
        Logger.log("Initializing scene model with observed data")

        # initialize cameras
        self.params.set_cameras(
            cam_data,
            opt_scale=self.opt_scale,
            opt_cams=self.opt_cams,
            opt_focal=self.opt_cams,
        )

        # initialize body params
        B, T = self.batch_size, self.seq_len
        device = next(iter(cam_data.values())).device
        init_betas = torch.mean(obs_data["init_body_shape"], dim=1) # torch.zeros(B, self.num_betas, device=device)

        if self.use_init and "init_body_pose" in obs_data:
            init_pose = obs_data["init_body_pose"][:, :, :J_HAND, :]
            init_pose_latent = self.pose2latent(init_pose)
        else:
            raise ValueError
            # init_pose = torch.zeros(B, T, J_HAND, 3, device=device)
            # init_pose_latent = torch.zeros(B, T, self.latent_pose_dim, device=device)

        # transform into world frame (T, 3, 3), (T, 3)
        R_w2c, t_w2c = cam_data["cam_R"], cam_data["cam_t"]
        R_c2w = R_w2c.transpose(-1, -2)
        t_c2w = -torch.einsum("tij,tj->ti", R_c2w, t_w2c)

        if self.use_init and "init_root_orient" in obs_data:
            init_rot = obs_data["init_root_orient"]  # (B, T, 3)
            init_rot_mat = angle_axis_to_rotation_matrix(init_rot)
            print(R_c2w.shape, init_rot_mat.shape)
            init_rot_mat = torch.einsum("tij,btjk->btik", R_c2w, init_rot_mat)
            init_rot = rotation_matrix_to_angle_axis(init_rot_mat)
        else:
            raise ValueError
            # init_rot = (
            #     torch.tensor([np.pi, 0, 0], dtype=torch.float32)
            #     .reshape(1, 1, 3)
            #     .repeat(B, T, 1)
            # )

        init_trans = torch.zeros(B, T, 3, device=device)
        if self.use_init and "init_trans" in obs_data:
            # must offset by the root location before applying camera to world transform
            is_right = obs_data["is_right"]
            pred_data = self.pred_mano(init_trans, init_rot, init_pose, is_right, init_betas)
            root_loc = pred_data["joints3d"][..., 0, :]  # (B, T, 3)
            init_trans = obs_data["init_trans"]  # (B, T, 3)
            init_trans = (
                torch.einsum("tij,btj->bti", R_c2w, init_trans + root_loc)
                + t_c2w[None]
                - root_loc
            )
        else:
            # initialize trans with reprojected joints
            # pred_data = self.pred_mano(init_trans, init_rot, init_pose, init_betas)
            # init_trans = estimate_initial_trans(
            #     init_pose,
            #     pred_data["joints3d_op"],
            #     obs_data["joints2d"],
            #     obs_data["intrins"][:, 0],
            # )
            raise ValueError

        self.params.set_param("init_body_pose", init_pose)
        self.params.set_param("latent_pose", init_pose_latent)
        self.params.set_param("betas", init_betas)
        self.params.set_param("trans", init_trans)
        self.params.set_param("root_orient", init_rot)
        self.params.set_param("is_right", is_right, requires_grad=False)
        
        # Store initial latent pose in obs_data for pose prior loss
        obs_data["init_latent_pose"] = init_pose_latent.detach()
        # print(init_pose.shape, init_pose_latent.shape, init_betas.shape, init_trans.shape, init_rot.shape, is_right.shape)
        # raise ValueError

    def get_optim_result(self, **kwargs):
        """
        Collect predicted outputs (latent_pose, trans, root_orient, betas, body pose) into dict
        """
        print('running get_optim_result in base_scene.py...')
        res = self.params.get_dict()
        if "latent_pose" in res:
            res["pose_body"] = self.latent2pose(self.params.latent_pose).detach()

        # add the cameras
        res["cam_R"], res["cam_t"], _, _ = self.params.get_cameras()
        res["intrins"] = self.params.intrins
        return {"world": res}

    def latent2pose(self, latent_pose):
        """
        Converts VPoser latent embedding to aa body pose.
        latent_pose : B x T x D
        body_pose : B x T x J*3
        """
        if self.pose_prior is not None:
            B, T, _ = latent_pose.size()
            d_latent = self.pose_prior.latentD
            latent_pose = latent_pose.reshape((-1, d_latent))
            body_pose = self.pose_prior.decode(latent_pose, output_type="matrot")
            body_pose = rotation_matrix_to_angle_axis(
                body_pose.reshape((B * T * J_HAND, 3, 3))
            ).reshape((B, T, J_HAND * 3))
            return body_pose + self.hand_mean
        else:
            return latent_pose

    def pose2latent(self, body_pose):
        """
        Encodes aa body pose to VPoser latent space.
        body_pose : B x T x J*3
        latent_pose : B x T x D
        """
        if self.pose_prior is not None:
            B, T = body_pose.shape[:2]
            body_pose = body_pose.reshape((-1, J_HAND * 3))
            latent_pose_distrib = self.pose_prior.encode(body_pose - self.hand_mean)
            d_latent = self.pose_prior.latentD
            latent_pose = latent_pose_distrib.mean.reshape((B, T, d_latent))
            return latent_pose
        else:
            return body_pose

    def pred_mano(self, trans, root_orient, body_pose, is_right, betas):
        """
        Forward pass of the MANO model and populates pred_data accordingly with
        joints3d, verts3d, points3d.

        trans : B x T x 3
        root_orient : B x T x 3
        body_pose : B x T x J*3
        betas : B x D
        """

        mano_out = run_mano(self.body_model, trans, root_orient, body_pose, is_right, betas=betas)
        joints3d, points3d = mano_out["joints"], mano_out["vertices"]

        # select desired joints and vertices
        # joints3d_body = joints3d
        # joints3d_op = joints3d.clone()
        # joints3d_op = joints3d[:, :, self.smpl2op_map, :]
        # # hacky way to get hip joints that align with ViTPose keypoints
        # # this could be moved elsewhere in the future (and done properly)
        # joints3d_op[:, :, [9, 12]] = (
        #     joints3d_op[:, :, [9, 12]]
        #     + 0.25 * (joints3d_op[:, :, [9, 12]] - joints3d_op[:, :, [12, 9]])
        #     + 0.5
        #     * (
        #         joints3d_op[:, :, [8]]
        #         - 0.5 * (joints3d_op[:, :, [9, 12]] + joints3d_op[:, :, [12, 9]])
        #     )
        # )
        verts3d = points3d #[:, :, KEYPT_VERTS, :]

        return {
            "is_right": is_right,
            "points3d": points3d,  # all vertices
            "verts3d": verts3d,  # keypoint vertices
            "joints3d": joints3d,  # smpl joints
            "joints3d_op": joints3d,  # OP joints
            "l_faces": mano_out["l_faces"],  # index array of faces
            "r_faces": mano_out["r_faces"],  # index array of faces
            "body_pose": mano_out["body_pose"]
        }

    def pred_params_mano(self, is_right, reproj=True):
        body_pose = self.latent2pose(self.params.latent_pose)
        pred_data = self.pred_mano(
            self.params.trans, self.params.root_orient, body_pose, is_right, self.params.betas
        )
        # from geometry.mesh import save_mesh_scenes, vertices_to_trimesh
        # LIGHT_BLUE=(0.65098039,  0.74117647,  0.85882353)
        # print(pred_data.keys())
        # verts, l_faces, r_faces, is_right = pred_data['verts3d'], pred_data['l_faces'], pred_data['l_faces'], pred_data['is_right']
        # T = len(verts[0])
        # print(f"{T} mesh frames")
        # print(verts.shape, l_faces.shape, is_right.shape, is_right)
        # times = list(range(0, T, 1))
        # os.makedirs('./mesh/')
        # for t in times:

        #     tmesh = vertices_to_trimesh(verts[0][t].detach().cpu().numpy(), l_faces.detach().cpu().numpy(), LIGHT_BLUE, is_right=0)
        #     tmesh.export(os.path.join('./mesh/', f'{str(t).zfill(6)}_0.obj'))

        #     tmesh = vertices_to_trimesh(verts[1][t].detach().cpu().numpy(), r_faces.detach().cpu().numpy(), LIGHT_BLUE, is_right=1)
        #     tmesh.export(os.path.join('./mesh/', f'{str(t).zfill(6)}_1.obj'))
        #     print(os.path.join('./mesh/', f'{str(t).zfill(6)}_1.obj'))

        #################################
        # print(self.params.root_orient.shape, self.params.init_body_pose.shape, body_pose.shape, self.params.trans.shape, self.params.betas.shape)
        # hand_model = mano.load(
        #     model_path= '/vol/bitbucket/zy3023/code/hand/slam-hand/_DATA/data/mano',# '/vol/bitbucket/zy3023/code/hand/slam-hand/VPoser/pretrained/Vposer_right_mirrored',
        #     is_right=True,
        #     num_pca_comps=45,
        #     batch_size=1,
        #     flat_hand_mean=False,
        # ).cuda()

        # output = hand_model(
        #     betas=self.params.betas[0][None].repeat(180,1),
        #     global_orient=self.params.root_orient[0],
        #     hand_pose=self.params.init_body_pose[0].reshape(180, -1) - self.hand_mean,
        #     transl=self.params.trans[0],
        #     return_verts=True,
        #     return_tips=False
        # )
        # np.save('x.npy', self.params.init_body_pose[0].reshape(180, -1).detach().cpu().numpy())

        # out_path = './out'
        # h_meshes = hand_model.hand_meshes(output)
        # if not os.path.exists(out_path):
        #     os.mkdir(out_path + '_after')
        #     os.mkdir(out_path)

        # for i in range(180):
        #     #print(f"export to {out_path}/{str(i).zfill(6)}.ply")
        #     h_meshes[i].export(f"{out_path}/{str(i).zfill(6)}.ply")

        # # print(body_pose.shape, body_pose[0])
        # print(self.hand_mean)
        # output = hand_model(
        #     betas=self.params.betas[0][None].repeat(180,1),
        #     global_orient=self.params.root_orient[0],
        #     hand_pose=body_pose[0].reshape(180, -1) - self.hand_mean,
        #     transl=self.params.trans[0],
        #     return_verts=True,
        #     return_tips=False
        # )

        # h_meshes = hand_model.hand_meshes(output)
        # for i in range(180):
        #     #print(f"export to {out_path}_after/{str(i).zfill(6)}.ply")
        #     h_meshes[i].export(f"{out_path}_after/{str(i).zfill(6)}.ply")
        # exit()

        return pred_data
