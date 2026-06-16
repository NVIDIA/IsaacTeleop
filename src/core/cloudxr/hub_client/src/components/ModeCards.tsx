/*
 * SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
 * SPDX-License-Identifier: Apache-2.0
 */

import React from 'react';

import type { ClientMode } from '../types';

const MODES: Array<{ id: ClientMode; title: string; subtitle: string; note: string }> = [
  {
    id: 'desktop',
    title: 'Desktop',
    subtitle: 'Monitor + mouse · multi-camera operator console',
    note: 'No headset required',
  },
  {
    id: 'xr-headset',
    title: 'Immersive XR',
    subtitle: 'Headset on · stereo first-person · hand and controller tracking',
    note: 'Recommended for fine manipulation',
  },
  {
    id: 'neck-worn',
    title: 'Neck-worn',
    subtitle: 'Headset on the neck · hands-free · companion view',
    note: 'Good for long sessions and shared supervision',
  },
];

interface ModeCardsProps {
  mode: ClientMode;
  onModeChange: (mode: ClientMode) => void;
}

export function ModeCards({ mode, onModeChange }: ModeCardsProps) {
  return (
    <div className="mode-stack">
      {MODES.map(item => (
        <button
          key={item.id}
          type="button"
          className={`selection-card mode-card ${mode === item.id ? 'selected' : ''}`}
          onClick={() => onModeChange(item.id)}
        >
          <span className="mode-icon">{item.id === 'desktop' ? '▣' : item.id === 'neck-worn' ? '♙' : '⌁'}</span>
          <span>
            <strong>{item.title}</strong>
            <small>{item.subtitle}</small>
            <em>{item.note}</em>
          </span>
          <span className="radio-dot" />
        </button>
      ))}
    </div>
  );
}
