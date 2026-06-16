/*
 * SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
 * SPDX-License-Identifier: Apache-2.0
 */

import React from 'react';

import type { Badge as BadgeType } from '../types';

export function Badge({ label, tone }: BadgeType) {
  return <span className={`badge badge-${tone}`}>{label}</span>;
}
