/*
 * SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
 * SPDX-License-Identifier: Apache-2.0
 */

import React from 'react';

import { activeClient, bestJoinLinkForHub, valueText } from '../api';
import type { ClientMode, HubState } from '../types';
import { Badge } from './Badge';

interface JoinStepProps {
  state: HubState;
  mode: ClientMode;
  clientKind: string;
  onClientKindChange: (kind: string) => void;
  onBack: () => void;
  onContinue: () => void;
}

function shortCode(link: string | undefined) {
  if (!link) return '------';
  let hash = 0;
  for (const ch of link) hash = (hash * 31 + ch.charCodeAt(0)) % 2176782336;
  return hash.toString(36).toUpperCase().padStart(6, '0').slice(-6).replace(/(.{3})/, '$1-');
}

export function JoinStep({ state, mode, clientKind, onClientKindChange, onBack, onContinue }: JoinStepProps) {
  const link = bestJoinLinkForHub(state, clientKind);
  const client = activeClient(state);
  const title =
    mode === 'neck-worn'
      ? 'Put the headset on your neck, then open the link'
      : 'Open this session in your headset';

  return (
    <section className="flow-screen join-layout">
      <div className="primary-pane">
        <div className="badge-row">
          <Badge label={client ? 'Client registered' : 'Waiting for headset'} tone={client ? 'live' : 'warn'} />
          <Badge label={mode === 'neck-worn' ? 'Neck-worn' : 'Immersive XR'} tone="mock" />
          <Badge label="GR-1 Humanoid" tone="mock" />
        </div>
        <h1>{title}</h1>
        <p className="lede">
          The headset opens the same session. Mode, embodiment label, and pre-flight context carry
          over from this hub.
        </p>
        <ol className="instruction-list">
          <li>
            <div className="instruction-copy">
              <b>Put on the headset</b>
              <span>Use the headset browser or companion app.</span>
            </div>
          </li>
          <li>
            <div className="instruction-copy">
              <b>Open the session link</b>
              <span>Scan the QR code or copy the full client link.</span>
            </div>
          </li>
          <li>
            <div className="instruction-copy">
              <b>{mode === 'neck-worn' ? 'Tap Control only' : 'Tap Enter immersive'}</b>
              <span>{mode === 'neck-worn' ? 'This screen becomes the companion view.' : 'Calibration starts after the headset joins.'}</span>
            </div>
          </li>
        </ol>
        <div className="link-strip">
          <div>
            <small>Session link</small>
            <code>{valueText(link?.href, 'waiting for client URL')}</code>
          </div>
          <div>
            <small>Future short code</small>
            <b>{shortCode(link?.href)}</b>
            <span className="mock-note">Mock until the hub has a resolver.</span>
          </div>
        </div>
        <div className="footer-actions">
          <button className="ghost-button" type="button" onClick={onBack}>Back</button>
          <button className="primary-button" type="button" onClick={onContinue}>Continue to pre-flight ›</button>
        </div>
      </div>
      <aside className="side-pane device-pane">
        <div className="qr-card" aria-label="Mock QR code">
          {Array.from({ length: 81 }).map((_, index) => (
            <span key={index} className={(index * 7 + index) % 5 < 2 ? 'on' : ''} />
          ))}
        </div>
        <p className="muted center">Scan with the headset browser or Teleop companion app.</p>
        <div className="client-choice">
          <button
            className={clientKind === 'local-hosted' ? 'active' : ''}
            type="button"
            onClick={() => onClientKindChange('local-hosted')}
          >
            Hosted
          </button>
          <button
            className={clientKind === 'github-pages' ? 'active' : ''}
            type="button"
            onClick={() => onClientKindChange('github-pages')}
          >
            Public
          </button>
        </div>
        <div className="device-list">
          <p className="eyebrow">Devices in this session</p>
          <div className="device-row"><span className="small-icon">▣</span><b>This computer</b><small>Companion · connected</small><i /></div>
          <div className="device-row"><span className="small-icon">⌁</span><b>Headset</b><small>{client ? 'registered' : 'waiting...'}</small><i className={client ? 'ok' : ''} /></div>
        </div>
        <div className="info-callout">No headset handy? Switch to desktop mode and drive from this screen.</div>
      </aside>
    </section>
  );
}
