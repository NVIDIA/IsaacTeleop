/*
 * SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
 * SPDX-License-Identifier: Apache-2.0
 */

import React from 'react';

import { valueText } from '../api';
import type { ClientMode, HubState } from '../types';
import { Badge } from './Badge';

interface LiveStepProps {
  state: HubState;
  mode: ClientMode;
  onBack: () => void;
}

export function LiveStep({ state, mode, onBack }: LiveStepProps) {
  const metrics = state.metrics ?? {};
  const streaming = Boolean(metrics.streamingClients);

  return (
    <section className="flow-screen live-layout">
      <div className="primary-pane">
        <div className="badge-row">
          <Badge label={streaming ? 'Streaming' : 'Ready'} tone={streaming ? 'live' : 'warn'} />
          <Badge label={mode} tone="mock" />
          <Badge label="Commands not wired" tone="mock" />
        </div>
        <h1>{streaming ? 'Teleop session live' : 'Ready to start teleop'}</h1>
        <p className="lede">
          Monitor one active client, stream health, and safety controls from the hub.
        </p>
        <div className="metric-grid">
          <div><small>Clients</small><b>{metrics.clientsConnected ?? 0}</b></div>
          <div><small>Streaming</small><b>{metrics.streamingClients ?? 0}</b></div>
          <div><small>Frame rate</small><b>{metrics.frameRate == null ? '-' : `${metrics.frameRate} fps`}</b></div>
          <div><small>Latency</small><b>{metrics.latencyMs == null ? '-' : `${metrics.latencyMs} ms`}</b></div>
        </div>
        <div className="footer-actions">
          <button className="ghost-button" type="button" onClick={onBack}>Back</button>
          <button className="danger-button" type="button" disabled>Software E-stop</button>
          <button className="ghost-button" type="button" disabled>Disconnect</button>
        </div>
      </div>
      <aside className="side-pane">
        <p className="eyebrow">Session status</p>
        <h2>{valueText(state.session?.displayName, state.app?.displayName ?? 'Isaac Teleop')}</h2>
        <div className="mini-grid">
          <div><small>Runtime</small><b>{valueText(state.session?.runtime, 'CloudXR')}</b></div>
          <div><small>Server</small><b>{valueText(state.config?.serverIP, 'waiting')}</b></div>
          <div><small>TeleViz</small><b>{state.televiz?.present ? 'present' : 'not reported'}</b></div>
          <div><small>Codec</small><b>{valueText(state.config?.codec, 'default')}</b></div>
        </div>
        <div className="info-callout">
          Software E-stop and lifecycle actions need the app-provided lifecycle adapter before they
          can be enabled.
        </div>
      </aside>
    </section>
  );
}
