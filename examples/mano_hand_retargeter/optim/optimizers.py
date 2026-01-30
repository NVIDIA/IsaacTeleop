import os
import glob
import numpy as np
import matplotlib.pyplot as plt

import torch
import torch.nn as nn
import torch.nn.functional as F
import torch.optim as optim

from body_model import OP_IGNORE_JOINTS
from geometry.mesh import save_mesh_scenes, vertices_to_trimesh
from util.logger import Logger, log_cur_stats
from util.tensor import move_to, detach_all
from vis.output import prep_result_vis, animate_scene

from .losses import RootLoss, SMPLLoss #, MotionLoss
from .output import save_camera_json
import time

LINE_SEARCH = "strong_wolfe"
LIGHT_BLUE=(0.65098039,  0.74117647,  0.85882353)

"""
Optimization happens in multiple stages
Stage 1: fit root orients and trans of each frame indendpently 
Stage 2: fit SMPL poses and betas of each frame independently
Stage 3: fit poses and roots in same global coordinate frame
"""


class StageOptimizer(object):
    def __init__(
        self,
        name,
        model,
        param_names,
        lr=1.0,
        lbfgs_max_iter=20,
        save_every=10,
        vis_every=-1,
        save_meshes=True,
        max_chunk_steps=10,
        **kwargs,
    ):
        Logger.log(f"INITIALIZING OPTIMIZER {name} for {param_names}")
        self.name = name
        self.model = model

        self.set_opt_vars(param_names)

        self.optim = torch.optim.LBFGS(
            self.opt_params, max_iter=lbfgs_max_iter, lr=lr, line_search_fn=LINE_SEARCH
        )
        # LBFGS computes losses multiple times per iteration,
        # save a dict mapping iteration to list of stats_dicts
        self.loss_dicts = {}

        self.save_every = save_every
        self.vis_every = vis_every
        self.save_meshes = save_meshes
        self.max_chunk_steps = max_chunk_steps

        self.cur_step = 0

        self.add_chunk = 0
        self.cur_loss = 0
        self.prev_loss = np.inf
        self.last_updated = 0
        self.reached_max = False
        self.reached_max_iter = -1

    def set_opt_vars(self, param_names):
        Logger.log("Set param names:")
        Logger.log(param_names)

        self.param_names = param_names
        self.model.params.set_require_grads(self.param_names)
        self.opt_params = [
            getattr(self.model.params, name) for name in self.param_names
        ]

    def forward_pass(self, obs_data):
        raise NotImplementedError

    def load_checkpoint(self, out_dir, device=None):
        if device is None:
            device = torch.device("cpu")

        param_path = os.path.join(out_dir, f"{self.name}_params.pth")
        if os.path.isfile(param_path):
            param_dict = torch.load(param_path, map_location=device)
            self.model.params.load_dict(param_dict)
            Logger.log(f"Params loaded from {param_path}")

        optim_path = os.path.join(out_dir, f"{self.name}_optim.pth")
        if os.path.isfile(optim_path):
            optim_dict = torch.load(optim_path)
            self.optim.load_state_dict(optim_dict["optim"])
            self.cur_step = optim_dict["cur_step"]
            Logger.log(f"Optimizer loaded from {optim_path} at iter {self.cur_step}")

    def save_checkpoint(self, out_dir):
        param_path = os.path.join(out_dir, f"{self.name}_params.pth")
        param_dict = self.model.params.get_dict()
        if "world_scale" in param_dict:
            print("WORLD_SCALE", param_dict["world_scale"].detach().cpu())
        if "floor_plane" in param_dict:
            print("FLOOR PLANE", param_dict["floor_plane"].detach().cpu())
        if "cam_f" in param_dict:
            print("CAM_F", param_dict["cam_f"].detach().cpu())
        torch.save(param_dict, param_path)
        Logger.log(f"Model saved at {param_path}")

        optim_path = os.path.join(out_dir, f"{self.name}_optim.pth")
        torch.save(
            {"optim": self.optim.state_dict(), "cur_step": self.cur_step},
            optim_path,
        )
        Logger.log(f"Optimizer saved at {optim_path}")

    def save_results(self, out_dir, seq_name):
        """
        pred dict will be a dictionary of trajectories.
        each trajectory will have params and lists of trimesh sequences
        """
        os.makedirs(out_dir, exist_ok=True)

        with torch.no_grad():
            print('go into get_optim_result from optimizer.py save_results')
            pred_dict = self.model.get_optim_result()
        pred_dict = move_to(detach_all(pred_dict), "cpu")

        i = self.cur_step
        for name, results in pred_dict.items():
            print('save_results, name: ', name)
            # save parameters of trajectory
            out_path = f"{out_dir}/{seq_name}_{i:06d}_{name}_results.npz"
            Logger.log(f"saving params to {out_path}")
            np.savez(out_path, **results)
            print('cam_R in save_results and its .npz', results['cam_R'])

        # also save the cameras
        # print('save the cameras in ptimizer.py save_results')
        # print(self.model.params)
        # with torch.no_grad():
        #     cam_R, cam_t = self.model.params.get_extrinsics()
        #     intrins = self.model.params.get_intrinsics()
        # print('cam_R in 0000.json:', cam_R)
        # save_camera_json(
        #     f"{out_dir}/{seq_name}_cameras_{self.cur_step:06d}.json",
        #     cam_R.detach().cpu(),
        #     cam_t.detach().cpu(),
        #     intrins.detach().cpu(),
        # )

        # plot losses
        self.plot_losses(out_dir)

    # def save_meshes_all(self, res_dir, obs_data, seq_name, num_steps=-1):

    #     # check which results are saved
    #     seq_name = obs_data["seq_name"][0]
    #     res_pre = f"{res_dir}/{seq_name}_opt_{self.cur_step:06d}"
    #     with torch.no_grad():
    #         print('go into get_optim_result from optimizer.py vis_result')
    #         pred_dict = self.model.get_optim_result(num_steps=num_steps)

    #     res_dict = detach_all(pred_dict["world"])
    #     scene_dict = move_to(
    #         prep_result_vis(
    #             res_dict,
    #             obs_data["vis_mask"],
    #             obs_data["track_id"],
    #             self.model.body_model,
    #             temporal_smooth=True
    #         ),
    #         "cpu",
    #     )

    #     # save the meshes
    #     os.makedirs(res_dir, exist_ok=True)
    #     i = self.cur_step
    #     scene_dir = f"{res_dir}/{seq_name}_{i:06d}_meshes"
    #     os.makedirs(scene_dir, exist_ok=True)

    #     verts, joints, colors, l_faces, r_faces, is_right, bounds = scene_dict["geometry"]
    #     T = len(verts)
    #     print(f"{T} mesh frames")
    #     times = list(range(0, T, 1))
    #     for t in times:
    #         if len(is_right[t]) > 1:
    #             assert (is_right[t].cpu().numpy().tolist() == [0,1])
    #             # l_meshes = make_batch_mesh(verts[t][0][None], l_faces[t], colors[t][0][None])
    #             # r_meshes = make_batch_mesh(verts[t][1][None], r_faces[t], colors[t][1][None])
    #             # assert len(l_meshes) == 1
    #             # assert len(r_meshes) == 1
    #             tmesh = vertices_to_trimesh(verts[t][0].detach().cpu().numpy(), l_faces[t].detach().cpu().numpy(), LIGHT_BLUE, is_right=0)
    #             tmesh.export(os.path.join(scene_dir, f'{str(t).zfill(6)}_0.obj'))

    #             tmesh = vertices_to_trimesh(verts[t][1].detach().cpu().numpy(), r_faces[t].detach().cpu().numpy(), LIGHT_BLUE, is_right=1)
    #             tmesh.export(os.path.join(scene_dir, f'{str(t).zfill(6)}_1.obj'))

    #         else:
    #             assert len(is_right[t]) == 1
    #             if is_right[t] == 0:
    #                 # meshes = make_batch_mesh(verts[t][0][None], l_faces[t], colors[t][0][None])
    #                 tmesh = vertices_to_trimesh(verts[t][0].detach().cpu().numpy(), l_faces[t].detach().cpu().numpy(), LIGHT_BLUE, is_right=0)
    #                 tmesh.export(os.path.join(scene_dir, f'{str(t).zfill(6)}_0.obj'))
    #             elif is_right[t] == 1:
    #                 # meshes = make_batch_mesh(verts[t][0][None], r_faces[t], colors[t][0][None])
    #                 tmesh = vertices_to_trimesh(verts[t][0].detach().cpu().numpy(), r_faces[t].detach().cpu().numpy(), LIGHT_BLUE, is_right=1)
    #                 tmesh.export(os.path.join(scene_dir, f'{str(t).zfill(6)}_1.obj'))

    def vis_result(self, res_dir, obs_data, vis=None, num_steps=-1):
        if vis is None or self.vis_every < 0:
            return

        # check which results are saved
        seq_name = obs_data["seq_name"][0]
        res_pre = f"{res_dir}/{seq_name}_opt_{self.cur_step:06d}"
        with torch.no_grad():
            print('go into get_optim_result from optimizer.py vis_result')
            pred_dict = self.model.get_optim_result(num_steps=num_steps)

        res_dict = detach_all(pred_dict["world"])
        scene_dict = move_to(
            prep_result_vis(
                res_dict,
                obs_data["vis_mask"],
                obs_data["track_id"],
                self.model.body_model,
            ),
            "cpu",
        )
        animate_scene(vis, scene_dict, res_pre, render_views=["src_cam", "above"])

    def log_losses(self, stats_dict):
        stats_dict = move_to(detach_all(stats_dict), "cpu")
        log_cur_stats(
            stats_dict,
            iter=self.cur_step,
            to_stdout=(self.cur_step % self.save_every == 0),
        )
        for loss_name, loss_val in stats_dict.items():
            loss_dict = self.loss_dicts.get(loss_name, {})
            loss_series = loss_dict.get(self.cur_step, [])
            loss_series.append(loss_val)
            loss_dict[self.cur_step] = loss_series
            self.loss_dicts[loss_name] = loss_dict

    def record_current_losses(self, writer):
        """
        record the mean of current step's loss values in tensorboard
        """
        if len(self.loss_dicts) < 1:
            return

        for loss_name, loss_dict in self.loss_dicts.items():
            loss_mean = np.mean(loss_dict[self.cur_step])
            writer.add_scalar(f"{self.name}/{loss_name}", loss_mean, self.cur_step)

    def plot_losses(self, res_dir):
        """
        plot a box plot for each BFGS iteration
        """
        if len(self.loss_dicts) < 1:
            return
        for loss_name, loss_dict in self.loss_dicts.items():
            # times (list len T)
            # loss vals (list len T of loss value lists)
            times, loss_vals = zip(*loss_dict.items())
            plt.figure()
            plt.boxplot(loss_vals, labels=times, showfliers=False)
            plt.savefig(f"{res_dir}/{loss_name}.png")

    def run(self, obs_data, num_iters, out_dir, vis=None, writer=None):
        self.cur_step = 0
        self.loss.cur_step = 0
        res_dir = os.path.join(out_dir, self.name)
        os.makedirs(res_dir, exist_ok=True)
        seq_name = obs_data["seq_name"][0]
        print("SEQ NAME", seq_name, "num_iters", num_iters)

        # try to load from checkpoint if exists
        device = obs_data["joints2d"].device
        self.load_checkpoint(out_dir, device=device)

        if self.cur_step >= num_iters:
            Logger.log(f"Current optimizer {self}")
            Logger.log(f"Checkpoint at {self.cur_step} >= {num_iters}, skipping")
            return

        Logger.log(f"OPTIMIZING {self.name} FOR {num_iters} ITERATIONS")
        # time.sleep(5)

        # save initial results and vis
        print('go into save_results in optimizers.py run()')
        self.save_results(res_dir, seq_name)

        for i in range(self.cur_step, num_iters):
            Logger.log("ITER: %d" % (i))

            if (i + 1) % self.save_every == 0:  # save before
                self.save_checkpoint(out_dir)
                self.save_results(res_dir, seq_name)
            else:
                self.save_checkpoint(out_dir)

            if (i + 1) % self.vis_every == 0:  # render
                self.vis_result(res_dir, obs_data, vis)

            self.cur_step = i
            self.loss.cur_step = i

            #print("ITER: %d" % (i))
            self.optim_step(obs_data, i, writer)

            # early termination in case of nans
            if np.isnan(self.cur_loss):
                # we need to backtrack
                self.load_checkpoint(out_dir, device=device)
                print(self.cur_loss, self.kkk, self.ppp)
                raise ValueError

            # termination for the last chunk
            if self.reached_max and self.reached_max_iter < 0:
                self.reached_max_iter = i - 1
            if self.reached_max and i - self.reached_max_iter >= self.max_chunk_steps:
                break

            # termination for middle chunks
            loss_change = self.prev_loss - self.cur_loss
            if self.last_updated == i - 1 and loss_change == 0:
                break
            if (
                (self.cur_loss < 0 and loss_change < 100)
                or (i - self.last_updated >= self.max_chunk_steps)
                or (loss_change < 20 and i - self.last_updated > 5)
            ):
                self.add_chunk = self.add_chunk + 1
                self.last_updated = i
            self.prev_loss = self.cur_loss

        # final save and vis step
        self.cur_step = num_iters
        self.save_checkpoint(out_dir)
        self.save_results(res_dir, seq_name)
        self.vis_result(res_dir, obs_data, vis)
        # self.save_meshes_all(res_dir, obs_data, seq_name)

    def optim_step(self, obs_data, i, writer=None):
        def closure():
            self.optim.zero_grad()
            #print('******************************', i)
            loss, stats_dict, preds = self.forward_pass(obs_data)
            #print('******************************', i)
            stats_dict["total"] = loss
            self.log_losses(move_to(detach_all(stats_dict), "cpu"))
            self.cur_loss = stats_dict["total"].detach().cpu().item()
            self.kkk = stats_dict
            self.ppp = preds
            loss_keys = stats_dict.keys()
            if "motion_prior" in loss_keys and "pose_prior" in loss_keys:
                self.cur_loss = (
                    self.cur_loss
                    - 0.04 * stats_dict["pose_prior"].detach().cpu().item()
                )
            print("optimizer print", loss, loss.shape, stats_dict, loss.requires_grad)
            loss.backward()
            # print('end of loss backward')
            return loss

        #print('!!!!!!!!!!!!!!!!!!!!!!!!!!', i)
        self.optim.step(closure)
        #print('!!!!!!!!!!!!!!!!!!!!!!!!!!', i)
        if writer is not None:
            self.record_current_losses(writer)


class RootOptimizer(StageOptimizer):
    name = "root_fit"
    stage = 0

    def __init__(
        self,
        model,
        all_loss_weights,
        use_chamfer=False,
        robust_loss_type="none",
        robust_tuning_const=4.6851,
        joints2d_sigma=100,
        **kwargs,
    ):
        param_names = ["trans", "root_orient"]
        super().__init__(self.name, model, param_names, **kwargs)

        self.loss = RootLoss(
            all_loss_weights[self.stage],
            ignore_op_joints=OP_IGNORE_JOINTS,
            joints2d_sigma=joints2d_sigma,
            use_chamfer=use_chamfer,
            robust_loss=robust_loss_type,
            robust_tuning_const=robust_tuning_const,
            faces=model.body_model.faces_tensor
        )

    def forward_pass(self, obs_data):
        """
        Takes in observed data, predicts the smpl parameters and returns loss
        """
        # raise ValueError
        # Use current params to go through SMPL and get joints3d, verts3d, points3d
        pred_data = self.model.pred_params_mano(obs_data["is_right"])
        pred_data["cameras"] = self.model.params.get_cameras()

        # compute data losses only
        vis_mask = obs_data["vis_mask"] >= 0
        # print('entering loss from RootOptimizer')
        loss, stats_dict = self.loss(obs_data, pred_data, vis_mask)
        return loss, stats_dict, pred_data


class SmoothOptimizer(StageOptimizer):
    name = "smooth_fit"
    stage = 1

    def __init__(
        self,
        model,
        all_loss_weights,
        use_chamfer=False,
        robust_loss_type="none",
        robust_tuning_const=4.6851,
        joints2d_sigma=100,
        **kwargs,
    ):
        param_names = ["trans", "root_orient", "betas", "latent_pose"]
        if model.opt_scale:
            param_names += ["world_scale"]
        if model.opt_cams:
            param_names += ["cam_f", "delta_cam_R"]

        super().__init__(self.name, model, param_names, **kwargs)

        self.loss = SMPLLoss(
            all_loss_weights[self.stage],
            ignore_op_joints=OP_IGNORE_JOINTS,
            joints2d_sigma=joints2d_sigma,
            use_chamfer=use_chamfer,
            robust_loss=robust_loss_type,
            robust_tuning_const=robust_tuning_const,
            faces=model.body_model.faces_tensor
        )

    def forward_pass(self, obs_data):
        """
        Takes in observed data, predicts the smpl parameters and returns loss
        """
        # raise ValueError
        # Use current params to go through SMPL and get joints3d, verts3d, points3d
        pred_data = self.model.pred_params_mano(obs_data["is_right"])
        pred_data["cameras"] = self.model.params.get_cameras()
        pred_data.update(self.model.params.get_vars())

        # camera predictions
        #         pts_ij, target, weight = self.model.params.get_reprojected_points()
        #         pred_data["bg2d_err"] = (
        #             (weight * (pts_ij - target) ** 2).sum(dim=(-1, -2)).mean()
        #         )
        pred_data["cam_R"], pred_data["cam_t"] = self.model.params.get_extrinsics()

        # compute data losses only
        vis_mask = obs_data["vis_mask"] >= 0
        loss, stats_dict = self.loss(obs_data, pred_data, self.model.seq_len, vis_mask)
        return loss, stats_dict, pred_data


# class MotionOptimizer(StageOptimizer):
#     name = "motion_fit"
#     stage = 2

#     def __init__(self, model, all_loss_weights, opt_cams=False, **kwargs):
#         self.opt_cams = opt_cams and model.opt_cams
#         param_names = [
#             "trans",
#             "root_orient",
#             "latent_pose",
#             "trans_vel",
#             "root_orient_vel",
#             "joints_vel",
#             "betas",
#             "latent_motion",
#             "floor_plane",
#         ]
#         if model.opt_scale:
#             param_names += ["world_scale"]

#         if self.opt_cams:
#             Logger.log(f"{self.name} OPTIMIZING CAMERAS")
#             param_names += ["delta_cam_R", "cam_f"]

#         super().__init__(self.name, model, param_names, **kwargs)
#         self.set_loss(model, all_loss_weights[self.stage], **kwargs)

#     def set_loss(
#         self,
#         model,
#         loss_weights,
#         use_chamfer=False,
#         robust_loss_type="none",
#         robust_tuning_const=4.6851,
#         joints2d_sigma=100,
#         **kwargs,
#     ):
#         self.loss = MotionLoss(
#             loss_weights,
#             init_motion_prior=model.init_motion_prior,
#             ignore_op_joints=OP_IGNORE_JOINTS,
#             joints2d_sigma=joints2d_sigma,
#             use_chamfer=use_chamfer,
#             robust_loss=robust_loss_type,
#             robust_tuning_const=robust_tuning_const,
#         )

#     def get_motion_scale(self):
#         return 1.0

#     def forward_pass(self, obs_data, num_steps=-1):
#         p = self.model.params
#         param_names = [
#             "betas",
#             "joints_vel",
#             "trans_vel",
#             "root_orient_vel",
#         ]
#         param_dict = p.get_vars(param_names)
#         # param_dict["floor_plane"] = p.floor_plane[p.floor_idcs]

#         preds, world_preds = self.model.rollout_mano_steps(num_steps)
#         preds.update(param_dict)
#         world_preds.update(param_dict)

#         # track mask is the length of the sequence that contains num_steps of each track
#         track_mask = world_preds.get("track_mask", None)
#         T = track_mask.shape[1] if track_mask is not None else num_steps
#         world_preds["cameras"] = p.get_cameras(np.arange(T))
#         if self.opt_cams:
#             cam_R, cam_t = p.get_extrinsics()
#             world_preds["cam_R"], world_preds["cam_t"] = cam_R[:T], cam_t[:T]

#         obs_data = slice_dict(obs_data, 0, T)
#         motion_scale = self.get_motion_scale()
#         loss, stats_dict = self.loss(
#             obs_data,
#             preds,
#             world_preds,
#             self.model.seq_len,
#             valid_mask=track_mask,
#             init_motion_scale=motion_scale,
#         )
#         return loss, stats_dict, (preds, world_preds)


# def slice_dict(d, start, end):
#     out = d.copy()
#     for k, v in d.items():
#         if not isinstance(v, torch.Tensor) or v.ndim < 3 or v.shape[1] < end:
#             continue
#         out[k] = v[:, start:end]
#     return out


# class MotionOptimizerChunks(MotionOptimizer):
#     """
#     Incrementally optimize sequence in chunks (with all variables)
#     :param chunk_size (int) number of frames per chunk
#     :param init_steps (int) number of optimization steps to spend on first chunk
#     :param chunk_steps (int) number of opt steps to spend on subsequent chunks
#     """

#     name = "motion_chunks"
#     stage = 2

#     def __init__(self, *args, chunk_size=20, init_steps=20, chunk_steps=10, **kwargs):
#         self.chunk_size = chunk_size
#         self.init_steps = init_steps
#         self.chunk_steps = chunk_steps
#         super().__init__(*args, **kwargs)

#     @property
#     def num_iters(self):
#         num_chunks = int(np.ceil(self.model.seq_len / self.chunk_size)) + 1
#         return self.init_steps + self.chunk_steps * num_chunks

#     @property
#     def end_idx(self):
#         if self.cur_step < self.init_steps and self.add_chunk == 0:
#             return self.chunk_size
#         chunk_idx = max(
#             (self.cur_step - self.init_steps) // self.chunk_steps + 1, self.add_chunk
#         )
#         if int(np.ceil(self.model.seq_len / self.chunk_size)) == self.add_chunk:
#             self.reached_max = True
#         return min(self.chunk_size * (chunk_idx + 1), self.model.seq_len)

#     @property
#     def start_idx(self):
#         return 0

#     def get_motion_scale(self):
#         num_frames = self.end_idx - self.start_idx
#         return max(1.0, float(self.model.seq_len) / num_frames)

#     def forward_pass(self, obs_data):
#         return super().forward_pass(obs_data, num_steps=self.end_idx)

#     def vis_result(self, res_dir, obs_data, vis=None, **kwargs):
#         print("start, end", self.start_idx, self.end_idx)
#         return super().vis_result(res_dir, obs_data, vis=vis, num_steps=self.end_idx)


# class MotionOptimizerFreeze(MotionOptimizer):
#     """
#     Only optimizing a subset of parameters
#     """

#     name = "motion_freeze"
#     stage = 2

#     def __init__(self, model, all_loss_weights, no_contacts=True, **kwargs):
#         loss_weights = all_loss_weights[self.stage].copy()

#         if no_contacts:
#             loss_weights["contact_height"] = 0.0
#             loss_weights["contact_vel"] = 0.0

#         param_names = ["latent_motion", "betas", "trans", "floor_plane"]
#         if model.optim_scale:
#             param_names += ["world_scale"]

#         StageOptimizer.__init__(self, self.name, model, param_names, **kwargs)
#         self.set_loss(model, loss_weights, **kwargs)
