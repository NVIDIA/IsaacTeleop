#!/bin/bash
# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
#
# Setup script for Dyn-HaMR data files
# Run this inside the Docker container after first launch

set -e

echo "=========================================="
echo "Dyn-HaMR Data Setup"
echo "=========================================="
echo

# Create directory structure
echo "Creating directory structure..."
mkdir -p /home/appuser/Dyn-HaMR/_DATA/data/mano
mkdir -p /home/appuser/Dyn-HaMR/_DATA/BMC
mkdir -p /home/appuser/Dyn-HaMR/third-party/hamer/pretrained_models
echo "✓ Directories created"
echo

# Download detector.pt
echo "Downloading YOLO hand detector..."
if [ ! -f "/home/appuser/Dyn-HaMR/third-party/hamer/pretrained_models/detector.pt" ]; then
    wget https://huggingface.co/spaces/rolpotamias/WiLoR/resolve/main/pretrained_models/detector.pt \
        -P /home/appuser/Dyn-HaMR/third-party/hamer/pretrained_models/
    echo "✓ Detector downloaded"
else
    echo "✓ Detector already exists"
fi
echo

# Copy data from mounted outputs (if available)
echo "Checking for required data files in mounted volumes..."

if [ -f "/home/appuser/outputs/MANO_RIGHT.pkl" ]; then
    echo "Copying MANO model..."
    cp /home/appuser/outputs/MANO_RIGHT.pkl /home/appuser/Dyn-HaMR/_DATA/data/mano/
    echo "✓ MANO model copied"
else
    echo "⚠ MANO_RIGHT.pkl not found in /home/appuser/outputs/"
    echo "  Please download from: https://mano.is.tue.mpg.de/"
    echo "  Then copy to: <WORKSPACE>/outputs/MANO_RIGHT.pkl"
fi

if [ -d "/home/appuser/outputs/BMC" ]; then
    echo "Copying BMC data..."
    cp /home/appuser/outputs/BMC/* /home/appuser/Dyn-HaMR/_DATA/BMC/
    echo "✓ BMC data copied"
else
    echo "⚠ BMC data not found in /home/appuser/outputs/"
    echo "  Please copy BMC files to: <WORKSPACE>/outputs/BMC/"
fi
echo

# Create placeholder CONVEX_HULLS if needed
if [ ! -f "/home/appuser/Dyn-HaMR/_DATA/BMC/CONVEX_HULLS.npy" ]; then
    echo "Creating placeholder CONVEX_HULLS.npy..."
    python << 'EOF'
import numpy as np
convex_hulls = [np.array([]) for _ in range(21)]
np.save("/home/appuser/Dyn-HaMR/_DATA/BMC/CONVEX_HULLS.npy", convex_hulls, allow_pickle=True)
EOF
    echo "✓ CONVEX_HULLS.npy created"
fi
echo

# Fix config paths
echo "Fixing config paths..."
sed -i 's|root: .*|root: /home/appuser/Dyn-HaMR/test|' \
    /home/appuser/Dyn-HaMR/dyn-hamr/confs/data/video_vipe.yaml
sed -i 's|vipe_dir: .*|vipe_dir: /home/appuser/outputs|' \
    /home/appuser/Dyn-HaMR/dyn-hamr/confs/data/video_vipe.yaml

# Verify the changes
echo "Verifying config changes:"
grep "vipe_dir:" /home/appuser/Dyn-HaMR/dyn-hamr/confs/data/video_vipe.yaml
echo "✓ Config paths fixed"
echo

# Disable HMP if not needed
echo "Disabling HMP (Human Motion Prior)..."
cd /home/appuser/Dyn-HaMR/dyn-hamr
if grep -q "^from HMP.fitting import run_prior" run_opt.py; then
    # Comment out all HMP-related imports using pattern matching
    sed -i 's|^from HMP.fitting import run_prior|# from HMP.fitting import run_prior|' run_opt.py
    sed -i 's|^from human_body_prior.tools.model_loader import load_model|# from human_body_prior.tools.model_loader import load_model|' run_opt.py
    sed -i 's|^from human_body_prior.models.vposer_model import VPoser|# from human_body_prior.models.vposer_model import VPoser|' run_opt.py
    sed -i '/^# from HMP.fitting import run_prior/a run_prior = None  # HMP disabled' run_opt.py
    echo "✓ HMP disabled in run_opt.py"
else
    echo "✓ HMP already disabled"
fi
echo

echo "=========================================="
echo "Setup Complete!"
echo "=========================================="
echo
echo "Verify data files:"
echo "  ls -lh /home/appuser/Dyn-HaMR/_DATA/data/mano/"
echo "  ls -lh /home/appuser/Dyn-HaMR/_DATA/BMC/"
echo "  ls -lh /home/appuser/Dyn-HaMR/third-party/hamer/pretrained_models/"
echo
echo "Run demo:"
echo "  cd /home/appuser/Dyn-HaMR/dyn-hamr"
echo "  python run_opt.py data=video_vipe run_opt=True run_vis=True data.seq=demo3 is_static=False"
