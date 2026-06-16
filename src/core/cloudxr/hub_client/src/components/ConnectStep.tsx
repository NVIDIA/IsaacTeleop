/*
 * SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
 * SPDX-License-Identifier: Apache-2.0
 */

import React from 'react';

import type { HubState } from '../types';
import { Badge } from './Badge';
import { RobotPreview } from './RobotPreview';

interface ConnectStepProps {
  state: HubState;
  serverTarget: string;
  onBack: () => void;
  onContinue: () => void;
}

const SAVED = [
  ['Lab-B · GR-1 bay 3', '10.0.31.42:8443', 'Real robot'],
  ['My workstation (sim)', '127.0.0.1:8443', 'Simulation'],
  ['Sim cluster · warehouse', 'ws-sim-01.lab:8443', 'Simulation'],
] as const;

export function ConnectStep({ state, serverTarget, onBack, onContinue }: ConnectStepProps) {
  return (
    <section className="flow-screen two-column">
      <div className="primary-pane">
        <p className="eyebrow">Step 2 of 4</p>
        <h1>Connect to a teleop server</h1>
        <p className="lede">
          Pick a saved server, enter an address, or let the client find available servers on the network.
        </p>
        <label className="server-input">
          <span>Server address</span>
          <input value={serverTarget} readOnly />
          <button type="button">Connect</button>
        </label>
        <p className="eyebrow">Saved servers</p>
        <div className="server-list">
          {SAVED.map(([name, address, kind], index) => (
            <button key={name} type="button" className={`server-row ${index === 0 ? 'selected' : ''}`}>
              <span>
                <b>{name}</b>
                <small>{address}</small>
              </span>
              <Badge label={kind} tone={kind === 'Real robot' ? 'live' : 'mock'} />
            </button>
          ))}
        </div>
        <div className="footer-actions">
          <button className="ghost-button" type="button" onClick={onBack}>Back</button>
          <button className="primary-button" type="button" onClick={onContinue}>Continue to pre-flight ›</button>
        </div>
      </div>
      <aside className="side-pane">
        <p className="eyebrow">Selected server</p>
        <h2>{state.app?.displayName ?? 'Isaac Teleop'}</h2>
        <code>{serverTarget}</code>
        <RobotPreview />
        <div className="mini-grid">
          <div><small>Link</small><b>reachable</b></div>
          <div><small>Latency</small><b>{state.metrics?.latencyMs ?? 11} ms</b></div>
          <div><small>Streams</small><b>{state.metrics?.frameRate ? 'live' : 'waiting'}</b></div>
          <div><small>Runtime</small><b>{state.session?.runtime ?? 'CloudXR'}</b></div>
        </div>
        <div className="info-callout">
          The app server owns robot power, fleet, and safety lifecycle. The hub connects and streams.
        </div>
      </aside>
    </section>
  );
}
