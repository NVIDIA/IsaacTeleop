import torch
from .specs import MANO_JOINTS


def run_mano(body_model, trans, root_orient, body_pose, is_right, betas=None):
    """
    Forward pass of the MANO model and populates pred_data accordingly with
    joints3d, verts3d, points3d.

    trans : B x T x 3
    root_orient : B x T x 3
    body_pose : B x T x J*3
    betas : (optional) B x D
    """
    B, T, _ = trans.shape
    bm_batch_size = body_model.batch_size
    assert bm_batch_size % B == 0
    # assert (is_right[0]==is_right[0][0]).all(), f'{is_right}'
    # assert (is_right[1]==is_right[1][0]).all(), f'{is_right}'

    seq_len = bm_batch_size // B
    bm_num_betas = body_model.num_betas
    J_BODY = len(MANO_JOINTS) - 1  # all joints except root
    # print('utils.py, seq_len, T: ', seq_len, T, bm_batch_size, B) # 1, 120, 1, 1
    # print('trans, root_orient, body_pose:', trans.shape, root_orient.shape, body_pose.shape)
    if T == 1:
        raise ValueError
        # must expand to use with body model
        trans = trans.expand(B, seq_len, 3)
        root_orient = root_orient.expand(B, seq_len, 3)
        body_pose = body_pose.expand(B, seq_len, J_BODY * 3)
    elif T != seq_len:
        trans, root_orient, body_pose = zero_pad_tensors(
            [trans, root_orient, body_pose], seq_len - T
        )
    if betas is None:
        betas = torch.zeros(B, bm_num_betas, device=trans.device)
    betas = betas.reshape((B, 1, bm_num_betas)).expand((B, seq_len, bm_num_betas))
    # print('body_pose: ', body_pose.reshape((B * seq_len, -1)).shape)

    mano_output = body_model(
        hand_pose=body_pose.reshape((B * seq_len, -1)),
        betas=betas.reshape((B * seq_len, -1)),
        global_orient=root_orient.reshape((B * seq_len, -1)),
        transl=trans.reshape((B * seq_len, -1)),
    )
    joints = mano_output.joints
    verts = mano_output.vertices

    joints = joints.reshape(B, seq_len, -1, 3)[:, :T]
    verts = verts.reshape(B, seq_len, -1, 3)[:, :T]

    is_right = is_right.unsqueeze(-1)
    joints[:, :, :, 0] = (2*is_right-1)*joints[:, :, :, 0]
    verts[:, :, :, 0] = (2*is_right-1)*verts[:, :, :, 0]

    return {
        "joints": joints,
        "vertices": verts,
        "l_faces": body_model.faces_tensor[:,[0,2,1]],
        "r_faces": body_model.faces_tensor,
        "is_right": is_right.squeeze(-1),
        'body_pose': body_pose.clone()
    }


def zero_pad_tensors(pad_list, pad_size):
    """
    Assumes tensors in pad_list are B x T x D and pad temporal dimension
    """
    B = pad_list[0].size(0)
    new_pad_list = []
    for pad_idx, pad_tensor in enumerate(pad_list):
        padding = torch.zeros((B, pad_size, pad_tensor.size(2))).to(pad_tensor)
        new_pad_list.append(torch.cat([pad_tensor, padding], dim=1))
    return new_pad_list
