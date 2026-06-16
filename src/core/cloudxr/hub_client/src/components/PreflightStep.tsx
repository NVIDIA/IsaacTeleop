/*
 * SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
 * SPDX-License-Identifier: Apache-2.0
 */

import React from 'react';

import { activeClient } from '../api';
import type { ClientMode, HubState } from '../types';
import { Badge } from './Badge';

interface PreflightStepProps {
  state: HubState;
  mode: ClientMode;
  onBack: () => void;
  onContinue: () => void;
}

export function PreflightStep({ state, mode, onBack, onContinue }: PreflightStepProps) {
  const client = activeClient(state);
  const hasClient = Boolean(client);
  const checks = [
    ['Headset / client', hasClient ? 'registered' : 'waiting for registration', hasClient],
    ['Input source', mode === 'desktop' ? 'mouse + keyboard' : 'hands / controllers', true],
    ['Reference frame', 'server-owned mapping', true],
    ['Will stream to server', state.config?.serverIP ? `${state.config.serverIP}:${state.config.port}` : 'waiting for target', Boolean(state.config?.serverIP)],
  ] as const;

  return (
    <section className="flow-screen two-column">
      <div className="primary-pane preflight-figure">
        <p className="eyebrow">Step 3 of 4 · client-side</p>
        <h1>Check your tracking before you stream</h1>
        <p className="lede">
          This validates the operator device locally. The server receives clean tracking once the
          session starts.
        </p>
        <div className="skeleton">
          <span className="head" />
          <span className="torso" />
          <span className="arm left" />
          <span className="arm right" />
          <span className="leg left" />
          <span className="leg right" />
        </div>
        <div className="tracking-bars">
          <span>Head</span><i /><span>Body</span><i /><span>Hand L</span><i /><span>Hand R</span><i />
        </div>
      </div>
      <aside className="side-pane">
        <div className="panel-title">
          <p className="eyebrow">Tracking validation</p>
          <Badge label={hasClient ? 'Live client state' : 'Waiting'} tone={hasClient ? 'live' : 'warn'} />
        </div>
        <div className="validation-list">
          {checks.map(([label, detail, ok]) => (
            <div key={label} className="validation-row">
              <span className={`check-dot ${ok ? 'ok' : ''}`}>{ok ? '✓' : '·'}</span>
              <span><b>{label}</b><small>{detail}</small></span>
            </div>
          ))}
        </div>
        <div className="info-callout">
          Capability-level tracking details are mocked until the WebXR client reports device and
          tracking validation fields.
        </div>
        <div className="footer-actions">
          <button className="ghost-button" type="button" onClick={onBack}>Back</button>
          <button className="primary-button" type="button" onClick={onContinue}>Start teleop ›</button>
        </div>
      </aside>
    </section>
  );
}
