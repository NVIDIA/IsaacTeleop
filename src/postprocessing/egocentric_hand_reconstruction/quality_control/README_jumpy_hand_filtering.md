<!--
SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
SPDX-License-Identifier: Apache-2.0
-->

# Jumpy Hand Filtering & Per-Frame Labels

This document describes the filtering and labeling process implemented in `detect_jumpy_hand_from_world_results.py`. The script analyzes Dyn-HaMR `*_world_results.npz` outputs to detect unstable (“jumpy”) hand tracks and produces per-frame boolean masks you can use for quality control or downstream filtering.

---

## What We Detect

We label frames along three kinds of issues:

### 1. Translation jump (per hand)

- **Definition:** A large change in hand **position** between consecutive frames.
- **Signal:** Adjacent-frame delta of `trans` (world-space root translation), as the L2 norm `‖trans[t] − trans[t−1]‖`.
- **Jump:** The delta exceeds a threshold (see [Thresholds](#thresholds)).

### 2. Rotation jump (per hand)

- **Definition:** A large change in hand **orientation** between consecutive frames.
- **Signal:** The relative rotation angle between `root_orient[t−1]` and `root_orient[t]` (axis-angle representation), i.e. the angle of `R[t−1]ᵀ R[t]`.
- **Jump:** That angle (in radians) exceeds a threshold.

### 3. Detection lost (per hand)

- **Definition:** The hand was not visible or not detected in that frame.
- **Source:** Not from the world_results NPZ; it comes from **`track_info.json`** in the same run directory. Each track has a `vis_mask`: `true` = visible/detected, `false` = lost. We expose this as a “detection” mask (see below).

Left and right hands are treated separately (using `is_right` from the NPZ, or track index when that is missing).

---

## Mask Convention

All per-frame outputs use the same convention:

- **`true`** = frame is **OK** (no jump, hand detected, or after filtering considered valid).
- **`false`** = frame is **bad** (jump, detection lost, or invalid after filtering).

So you can use the masks as “valid” flags: keep or use frames where the mask is `true`, and discard or downweight where it is `false`.

---

## Frame index: output frames ≠ raw video frames

**Frame 0 in the world_results NPZ and in the per-frame labels is not raw video frame 0.** The NPZ and labels use the **sequence interval** defined in `track_info.json`: `meta.seq_interval` is `[start, end)` in raw video frame indices. Output frame index `t` corresponds to **raw video frame `start + t`**. For example, if `seq_interval` is `[22, 949]`, then output frame 0 = raw frame 22, and the last output frame (index 926) = raw frame 948. When mapping labels or masks back to the original video, use `raw_frame = seq_interval[0] + t`.

---

## Pipeline: From Raw Detection to Final Valid Mask

The script builds several layers of masks. Conceptually:

```
Raw jump detection (per hand)
    → *_mask (frame-level: true = no jump, false = jump)
    → *_jump_interpolate_mask (fill 10-frame gaps between two jump frames with false)
Detection lost from track_info
    → *_detection_mask (true = detected, false = lost)
    ↓
valid_mask = AND of all 10 base masks (trans/rot + interpolated + detection, both hands)
    ↓
filtered_valid_mask = valid_mask with “single false” spikes removed (see below)
```

So:

1. **Raw jump masks**
   For each hand we get `left/right_hand_translation_mask` and `left/right_hand_rotation_mask`: `true` when that frame does **not** exceed the jump threshold.

2. **Jump-interpolate masks**
   For each of those four jump masks we build a `*_jump_interpolate_mask`: if frame `t` is a jump and there is another jump within the **next 10 frames** at `t'`, then every frame from `t` to `t'` is set to `false`. This fills short “normal” gaps between two nearby jumps so that the whole segment is labeled as invalid.

3. **Detection masks**
   From `track_info.json`, we get `left_hand_detection_mask` and `right_hand_detection_mask`: `true` when the hand is detected (visible) in that frame, `false` when it is lost.

4. **Valid mask**
   `valid_mask[t] = true` only when **all** of the following are `true` at frame `t`:
   - `left_hand_translation_mask`, `left_hand_rotation_mask`
   - `right_hand_translation_mask`, `right_hand_rotation_mask`
   - `left_hand_translation_jump_interpolate_mask`, `left_hand_rotation_jump_interpolate_mask`
   - `right_hand_translation_jump_interpolate_mask`, `right_hand_rotation_jump_interpolate_mask`
   - `left_hand_detection_mask`, `right_hand_detection_mask`
   So a frame is “valid” only if both hands are detected and pass both raw and interpolated jump checks.

5. **Filtered valid mask**
   `filtered_valid_mask` is derived from `valid_mask` by treating **single-frame false spikes** as `true`: if at frame `t` we have `valid_mask[t] = false` but **both** the previous 10 and the next 10 frames are all `true`, then we set `filtered_valid_mask[t] = true`. This removes isolated one-frame invalid labels that are often noise.

---

## Per-Frame Label Keys (in `qc_world_jumpy_per_frame_labels.json`)

| Key | Meaning |
|-----|--------|
| `left_hand_translation_mask` | `true` = no translation jump at this frame (left hand). |
| `left_hand_rotation_mask` | `true` = no rotation jump at this frame (left hand). |
| `right_hand_translation_mask` | Same for right hand translation. |
| `right_hand_rotation_mask` | Same for right hand rotation. |
| `left_hand_translation_jump_interpolate_mask` | Like above, but 10-frame gaps between two jump frames are also set to `false`. |
| `left_hand_rotation_jump_interpolate_mask` | Same for left rotation. |
| `right_hand_translation_jump_interpolate_mask` | Same for right translation. |
| `right_hand_rotation_jump_interpolate_mask` | Same for right rotation. |
| `left_hand_detection_mask` | `true` = left hand detected (from `track_info.json`). |
| `right_hand_detection_mask` | `true` = right hand detected (from `track_info.json`). |
| `valid_mask` | `true` only when all of the above 10 masks are `true` at this frame. |
| `filtered_valid_mask` | Like `valid_mask`, but single-frame `false` spikes (surrounded by 10 `true` on each side) are set to `true`. |

Each key is an array of booleans, one per frame index `0..T-1`.

---

## Output Files

### Per-run (single file or each video in batch)

- **`qc_world_jumpy_per_frame_labels.json`**
  Contains all per-frame mask arrays above. Written next to the world_results (or under `--out_dir` / `--out_subdir`).

- **`qc_world_jumpy_hand.json`** (optional, with `--json`)
  Summary report: selected “jumpy” track, thresholds, jump counts and frame lists, etc.

- **`qc_world_jumpy_deltas.png`** (optional, with `--plot`)
  Plots of per-frame translation and rotation deltas with thresholds.

### Batch only (when using `--world_results_dir`)

- **`qc_world_jumpy_batch_summary.json`**
  Written at the root of the folder you passed to `--world_results_dir`. It includes:
  - **Per video:** `world_results`, `video_id`, `num_frames`, `frames_false_by_key`, `trans_thr`, `rot_thr_deg`, and `error_video` (see below).
  - **Folder-level:** `median_trans_threshold`, `median_rot_threshold_deg`, `error_threshold_factor_trans`, `error_threshold_factor_rot`, and `error_video_ids`.

  **Error videos:** A video is labeled `error_video: true` (and its `video_id` added to `error_video_ids`) if any of:
  - `trans_thr > median_trans × error_threshold_factor_trans` (default 10.0), or
  - `rot_thr_deg > median_rot_deg × error_threshold_factor_rot` (default 10.0), or
  - More than 30% of frames are invalid: `filtered_invalid_ratio > error_valid_ratio` (default 0.3). Here `filtered_invalid_ratio` = (number of frames where `filtered_valid_mask` is false) / total_frames.

  Use `--error_threshold_factor_trans`, `--error_threshold_factor_rot`, and `--error_valid_ratio` to change these limits. Per-video `filtered_invalid_ratio` is stored in the summary.

### Merging per-result summaries (`merge_jumpy_batch_summaries.py`)

If you run jumpy detection **per result** (e.g. one `qc_world_jumpy_batch_summary.json` per run folder), you can merge them into one overall summary:

- **`merge_jumpy_batch_summaries.py`**
  Finds all `qc_world_jumpy_batch_summary.json` under a base directory, concatenates their `videos` lists, recomputes **median** trans/rot thresholds and **error_video** over the full set, and writes a single `qc_world_jumpy_batch_summary.json` at the base (or at `--out`).

  By default, each video’s **`video_id`** is set to the **folder name that contains** that summary (e.g. `2025-09-04-15-09-41-gr00t005-00013`), so error videos are identifiable by run folder.

---

## Thresholds

- **Translation:** By default the threshold is `median(translation deltas) × trans_factor`. Default `--trans_factor` is 20.0. You can override with `--trans_abs_threshold` (same units as `trans`).
- **Rotation:** Similarly, default is `median(rotation deltas) × rot_factor` (default 20.0). Override with `--rot_abs_threshold_deg` (degrees).

So “jump” = frame-to-frame delta above the chosen threshold. Tuning `--trans_factor` and `--rot_factor` (e.g. 20.0 for stricter labeling) controls sensitivity.

---

## Detection Lost and `track_info.json`

`left_hand_detection_mask` and `right_hand_detection_mask` are built from **`track_info.json`** in the run directory (typically `.../xxx-all-shot-0-0--1/track_info.json`). Each track has a `vis_mask` (one boolean per **raw** frame). The script uses **`meta.seq_interval`** when present: output frame `t` is taken from `vis_mask[seq_start + t]`, so detection masks align with the same sequence range as the NPZ (see [Frame index: output frames ≠ raw video frames](#frame-index-output-frames--raw-video-frames)). If `seq_interval` is missing, the first `num_frames` entries of `vis_mask` are used. We map tracks to left/right via `is_right` in the world_results NPZ (or by track index if `is_right` is missing). If `track_info.json` is not found, both detection masks are set to all `false` (all frames considered “lost” for that hand). You can point to a different file with `--track_info`.

---

## How to Run

**Single world_results file:**

```bash
python quality_control/detect_jumpy_hand_from_world_results.py \
  --world_results /path/to/smooth_fit/ego_view_000300_world_results.npz \
  --json --plot --out_dir /path/to/jumpy_hand \
  --trans_factor 20.0 --rot_factor 20.0
```

**Batch (all matching videos under a folder):**

Only files matching
`logs/video-custom/.../...-all-shot-0-0--1/smooth_fit/*_000300_world_results.npz`
under the given directory are processed. Outputs go under each run’s folder into a subdir named by `--out_subdir` (default `qc_results`). A single summary file is written at the root of the folder.

```bash
python quality_control/detect_jumpy_hand_from_world_results.py \
  --world_results_dir /path/to/first_50 \
  --json --plot --trans_factor 20.0 --rot_factor 20.0 --error_threshold_factor_trans 10.0 --error_threshold_factor_rot 1.1 --error_valid_ratio 0.3
```

Summary will be at `/path/to/first_50/qc_world_jumpy_batch_summary.json`, and each video’s per-frame labels at
`/path/to/first_50/<video_id>/logs/video-custom/.../...-all-shot-0-0--1/qc_results/qc_world_jumpy_per_frame_labels.json`.

**Per-result then merge (when you run detection separately per result):**

If you run detection per result so that each result has its own `qc_world_jumpy_batch_summary.json`, merge them into one overall summary with:

```bash
python quality_control/merge_jumpy_batch_summaries.py --world_results_dir /path/to/qc_jumpy_samples
```

- Discovers all `qc_world_jumpy_batch_summary.json` under the given directory (recursive).
- By default each video’s `video_id` is the **folder name** containing that summary (e.g. `2025-09-04-15-09-41-gr00t005-00013`).
- Writes `qc_world_jumpy_batch_summary.json` at the base (or `--out <path>`). You can then run `quality_control/cal_jumpy_proportions.py --world_results_dir /path/to/qc_jumpy_samples` (or `--summary <path>`) on the merged file.

Optional: `--error_threshold_factor_trans`, `--error_threshold_factor_rot`, `--error_valid_ratio` override the values used when recomputing `error_video`; otherwise the first summary’s params are used.

**Building a batch summary from existing `qc_results` only (no NPZ):**
If you have per-result `qc_results` dirs (with `qc_world_jumpy_per_frame_labels.json`) but no per-result batch summary files, you can still produce one summary without re-running on NPZ:
`python quality_control/detect_jumpy_hand_from_world_results.py --build_batch_from_qc_results --qc_results_base_dir /path/to/outputs`
See the script’s `--help` and docstring for details.

---

## Quick Reference: “Which mask should I use?”

- **Strict:** Use `valid_mask` — keep only frames where every condition (both hands, no translation/rotation jump including interpolated, and detected) is satisfied.
- **Relaxed:** Use `filtered_valid_mask` — same as above but single-frame false spikes are treated as valid.
- **Per-hand / per-type:** Use the individual `*_mask` or `*_jump_interpolate_mask` and `*_detection_mask` keys to filter or analyze by hand or by kind of failure (translation vs rotation vs detection lost).
