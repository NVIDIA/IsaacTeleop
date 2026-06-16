/*
 * SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
 * SPDX-License-Identifier: Apache-2.0
 */

import React from 'react';

import { valueText } from '../api';
import type { ClientMode, HubState } from '../types';
import { Badge } from './Badge';
import { ModeCards } from './ModeCards';
import { RobotPreview } from './RobotPreview';

interface ConfigureStepProps {
  state: HubState;
  mode: ClientMode;
  onModeChange: (mode: ClientMode) => void;
  onContinue: () => void;
}

const EMBODIMENTS = [
  ['GR-1 Humanoid', 'Bimanual · Head · 27 DoF', true],
  ['Franka Panda', 'Single arm · 7 DoF', false],
  ['Spot + Arm', 'Mobile manipulator · 13 DoF', false],
  ['H1 Walker', 'Bimanual · Legged · 19 DoF', false],
] as const;

export function ConfigureStep({ state, mode, onModeChange, onContinue }: ConfigureStepProps) {
  return (
    <section className="flow-screen two-column">
      <div className="primary-pane">
        <p className="eyebrow">Step 1 of 4</p>
        <h1>Start a teleop session</h1>
        <p className="lede">
          Choose how the operator will connect. The app server owns the robot lifecycle; the hub
          keeps the operator, headset, and stream state aligned.
        </p>
        <ModeCards mode={mode} onModeChange={onModeChange} />
        <div className="footer-actions">
          <button className="ghost-button" type="button">Load saved session...</button>
          <button className="primary-button" type="button" onClick={onContinue}>
            Continue to connect ›
          </button>
        </div>
      </div>
      <aside className="side-pane">
        <p className="eyebrow">Telemetry tag</p>
        <h2>Embodiment label</h2>
        <div className="info-callout">
          This label tags telemetry and datasets. The application server still owns the embodiment
          and lifecycle.
        </div>
        <RobotPreview />
        <div className="embodiment-list">
          {EMBODIMENTS.map(([name, detail, selected]) => (
            <button key={name} type="button" className={`selection-row ${selected ? 'selected' : ''}`}>
              <span className="small-icon">⌬</span>
              <span>
                <strong>{name}</strong>
                <small>{detail}</small>
              </span>
              <span className="radio-dot" />
            </button>
          ))}
        </div>
        <div className="mini-grid">
          <div>
            <small>Application server</small>
            <b>{valueText(state.config?.serverIP, 'waiting')}</b>
          </div>
          <div>
            <small>This device</small>
            <b>{mode === 'desktop' ? 'Desktop' : 'Companion'}</b>
          </div>
          <div>
            <small>Descriptor</small>
            <b>{valueText(state.app?.descriptorSource, 'stub')}</b>
          </div>
          <div>
            <small>Status</small>
            <b>{valueText(state.app?.status, 'ready')}</b>
          </div>
        </div>
        <div className="badge-row">
          <Badge label="Live app state" tone="live" />
          <Badge label="Mock embodiment picker" tone="mock" />
        </div>
      </aside>
    </section>
  );
}
