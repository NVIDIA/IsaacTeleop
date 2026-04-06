<!--
SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
SPDX-License-Identifier: Apache-2.0
-->

# cal_jumpy_proportions.py

Compute **true/false proportions** and **useful frames/seconds** from a jumpy-hand batch summary produced by `detect_jumpy_hand_from_world_results.py`.

---

## What it does

- **Input:** A `qc_world_jumpy_batch_summary.json` file (from running the detector with `--world_results_dir`).
- **Output:**
  - **Proportions:** For each mask key (e.g. `left_hand_translation_mask`, `filtered_valid_mask`), the fraction of frames that are `true` vs `false`, aggregated over all videos.
  - **Useful frames/seconds:** Count of frames where `filtered_valid_mask` is `true`, and (if `--fps` is set) the equivalent duration in seconds.

Statistics are reported in two ways:

1. **With error videos** — all videos in the summary.
2. **Excluding error videos** — only videos where `error_video` is `false`.

---

## Requirements

Run the jumpy-hand detector in batch mode first so that `qc_world_jumpy_batch_summary.json` exists:

```bash
python quality_control/detect_jumpy_hand_from_world_results.py \
  --world_results_dir /path/to/your/results \
  --json --plot --trans_factor 20.0 --rot_factor 20.0 \
  --error_threshold_factor_trans 10.0 --error_threshold_factor_rot 10.0 --error_valid_ratio 0.3
```

Then run this script on that summary (or on the same directory).

---

## Usage

**Point to the summary file directly:**

```bash
python quality_control/cal_jumpy_proportions.py --summary /path/to/qc_world_jumpy_batch_summary.json
```

**Point to the folder that contains the summary** (script looks for `qc_world_jumpy_batch_summary.json` inside it):

```bash
python quality_control/cal_jumpy_proportions.py --world_results_dir /path/to/your/results
```

**Save the report as JSON:**

```bash
python quality_control/cal_jumpy_proportions.py --summary /path/to/qc_world_jumpy_batch_summary.json --out proportions.json
```

**Include useful seconds** (requires frame rate):

```bash
python quality_control/cal_jumpy_proportions.py --summary /path/to/qc_world_jumpy_batch_summary.json --fps 30 --out proportions.json
```

---

## Options

| Option | Description |
|--------|-------------|
| `--summary PATH` | Path to `qc_world_jumpy_batch_summary.json`. |
| `--world_results_dir DIR` | Directory containing `qc_world_jumpy_batch_summary.json` (summary path = `DIR/qc_world_jumpy_batch_summary.json`). |
| `--out PATH` | Write the full report (proportions + useful stats) to this JSON file. |
| `--fps FLOAT` | Frames per second. If set, report `total_useful_seconds` and `total_seconds` in addition to frame counts. |

You must provide either `--summary` or `--world_results_dir`.

---

## Output

### Printed (stdout)

- Number of videos (total, excluding errors, error count).
- **Useful (filtered_valid_mask = true):** useful frames and total frames for “with error videos” and “excluding error videos”; if `--fps` is set, useful seconds and total seconds.
- Two tables of **proportions** (with / excluding error videos): for each mask key, `proportion_true`, `proportion_false`, and total frames.

### JSON (with `--out`)

The report object includes:

- `summary_path`, `num_videos_all`, `num_videos_excluding_error`, `num_error_videos`
- `useful_frames_with_error_videos`, `useful_frames_excluding_error_videos` — each with `total_frames`, `total_useful_frames`, and (if `--fps` was set) `total_seconds`, `total_useful_seconds`
- `fps` — value passed to `--fps` or `null`
- `proportions_with_error_videos`, `proportions_excluding_error_videos` — per-key stats: `total_frames`, `total_true`, `total_false`, `proportion_true`, `proportion_false`

---

## Mask keys

The mask keys come from the batch summary’s `frames_false_by_key` (same as in `detect_jumpy_hand_from_world_results.py`), e.g.:

- `left_hand_translation_mask`, `right_hand_translation_mask`
- `left_hand_rotation_mask`, `right_hand_rotation_mask`
- `left_hand_*_jump_interpolate_mask`, `right_hand_*_jump_interpolate_mask`
- `left_hand_detection_mask`, `right_hand_detection_mask`
- `left_hand_left_of_right_hand_mask`
- `valid_mask`, `filtered_valid_mask`

See [README_jumpy_hand_filtering.md](README_jumpy_hand_filtering.md) for what each mask means.
