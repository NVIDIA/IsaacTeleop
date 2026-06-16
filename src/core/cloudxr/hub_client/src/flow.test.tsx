/*
 * SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
 * SPDX-License-Identifier: Apache-2.0
 */

import React from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
import { describe, expect, it } from 'vitest';

import { bestJoinLinkForHub } from './api';
import { ConfigureStep } from './components/ConfigureStep';
import { ConnectStep } from './components/ConnectStep';
import { JoinStep } from './components/JoinStep';
import { LiveStep } from './components/LiveStep';
import { PreflightStep } from './components/PreflightStep';
import { Stepper } from './components/Stepper';
import { hashForStep, routeFromHash, stepFromHash } from './routing';
import type { HubState } from './types';

const state: HubState = {
  app: { displayName: 'Isaac Lab Pick Place', descriptorSource: 'app_descriptor', status: 'ready' },
  session: { displayName: 'Pick Place Session', runtime: 'CloudXR' },
  config: { serverIP: '10.0.0.8', port: 48322, codec: 'av1' },
  join: {
    links: [
      { kind: 'local-hosted', label: 'Hosted client', href: 'https://10.0.0.8:48322/client/?serverIP=10.0.0.8&port=48322&codec=av1' },
      { kind: 'github-pages', label: 'Public client', href: 'https://nvidia.github.io/IsaacTeleop/client/main/' },
    ],
  },
  clients: [
    {
      clientId: 'client-1',
      identity: { displayName: 'Quest 3' },
      stream: { streaming: false },
    },
  ],
  metrics: { clientsConnected: 1, streamingClients: 0, frameRate: 90, latencyMs: 8 },
  televiz: { present: true, mode: 'xr', state: 'ready' },
};

describe('Teleop Hub flow components', () => {
  it('renders the four-step flow navigation', () => {
    const html = renderToStaticMarkup(
      <Stepper
        activeStep="configure"
        onSelect={() => {}}
        status={{ configure: 'current', join: 'pending', preflight: 'pending', live: 'pending' }}
      />
    );
    expect(html).toContain('Configure');
    expect(html).toContain('Join / Connect');
    expect(html).toContain('Pre-flight');
    expect(html).toContain('Live');
  });

  it('renders configure mode and embodiment selection', () => {
    const html = renderToStaticMarkup(
      <ConfigureStep state={state} mode="xr-headset" onModeChange={() => {}} onContinue={() => {}} />
    );
    expect(html).toContain('Start a teleop session');
    expect(html).toContain('Immersive XR');
    expect(html).toContain('Neck-worn');
    expect(html).toContain('Embodiment label');
    expect(html).toContain('GR-1 Humanoid');
    expect(html).toContain('Mock embodiment picker');
  });

  it('renders headset join flow with hosted and public link choices', () => {
    const html = renderToStaticMarkup(
      <JoinStep
        state={state}
        mode="neck-worn"
        clientKind="local-hosted"
        onClientKindChange={() => {}}
        onBack={() => {}}
        onContinue={() => {}}
      />
    );
    expect(html).toContain('Put the headset on your neck');
    expect(html).toContain('Hosted');
    expect(html).toContain('Public');
    expect(html).toContain('instruction-copy');
    expect(html).toContain('Future short code');
    expect(html).toContain('Mock until the hub has a resolver');
    expect(html).toContain('Devices in this session');
  });

  it('resolves hosted client links from the current hub origin', () => {
    const localhostLink = bestJoinLinkForHub(state, 'local-hosted', 'https://localhost:48322/hub/#join');
    const workstationLink = bestJoinLinkForHub(state, 'local-hosted', 'https://10.24.68.12:48322/hub/#join');
    const devLink = bestJoinLinkForHub(state, 'local-hosted', 'http://localhost:5173/hub/#join');

    expect(localhostLink?.href).toBe('https://localhost:48322/client/?serverIP=10.0.0.8&port=48322&codec=av1');
    expect(workstationLink?.href).toBe('https://10.24.68.12:48322/client/?serverIP=10.0.0.8&port=48322&codec=av1');
    expect(devLink?.href).toBe('https://10.0.0.8:48322/client/?serverIP=10.0.0.8&port=48322&codec=av1');
  });

  it('maps hash URLs to flow steps', () => {
    expect(stepFromHash('#join')).toBe('join');
    expect(stepFromHash('#connect')).toBe('join');
    expect(routeFromHash('#connect').mode).toBe('desktop');
    expect(routeFromHash('#neck-worn').mode).toBe('neck-worn');
    expect(stepFromHash('#pre-flight')).toBe('preflight');
    expect(stepFromHash('#live')).toBe('live');
    expect(stepFromHash('#unknown')).toBe('configure');
    expect(hashForStep('preflight')).toBe('#preflight');
  });

  it('renders desktop server connect flow', () => {
    const html = renderToStaticMarkup(
      <ConnectStep state={state} serverTarget="10.0.0.8:48322" onBack={() => {}} onContinue={() => {}} />
    );
    expect(html).toContain('Connect to a teleop server');
    expect(html).toContain('Saved');
    expect(html).toContain('Real robot');
    expect(html).toContain('Continue to pre-flight');
  });

  it('renders preflight and live safety labels', () => {
    const preflight = renderToStaticMarkup(
      <PreflightStep state={state} mode="xr-headset" onBack={() => {}} onContinue={() => {}} />
    );
    const live = renderToStaticMarkup(<LiveStep state={state} mode="xr-headset" onBack={() => {}} />);
    expect(preflight).toContain('Check your tracking before you stream');
    expect(preflight).toContain('Tracking validation');
    expect(preflight).toContain('Start teleop');
    expect(live).toContain('Software E-stop');
    expect(live).toContain('Commands not wired');
  });
});
