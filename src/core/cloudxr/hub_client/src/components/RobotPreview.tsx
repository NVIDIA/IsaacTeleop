/*
 * SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
 * SPDX-License-Identifier: Apache-2.0
 */

import React from 'react';

export function RobotPreview() {
  return (
    <div className="robot-preview" aria-label="Reference robot preview">
      <div className="robot-head" />
      <div className="robot-body" />
      <div className="robot-arm left" />
      <div className="robot-arm right" />
      <div className="robot-leg left" />
      <div className="robot-leg right" />
      <div className="floor-grid" />
    </div>
  );
}
