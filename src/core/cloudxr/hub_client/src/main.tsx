/*
 * SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
 * SPDX-License-Identifier: Apache-2.0
 */

import React, { useEffect, useMemo, useState } from 'react';
import { createRoot } from 'react-dom/client';

import { activeClient, fetchHubState } from './api';
import { ConfigureStep } from './components/ConfigureStep';
import { ConnectStep } from './components/ConnectStep';
import { JoinStep } from './components/JoinStep';
import { LiveStep } from './components/LiveStep';
import { PreflightStep } from './components/PreflightStep';
import { Shell } from './components/Shell';
import { Stepper } from './components/Stepper';
import { hashForStep, routeFromHash } from './routing';
import type { ClientMode, FlowStep, HubState } from './types';

import './styles.css';

const POLL_MS = 1500;

function useHubState() {
  const [state, setState] = useState<HubState>({});
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let disposed = false;
    async function refresh() {
      try {
        const next = await fetchHubState();
        if (!disposed) {
          setState(next);
          setError(null);
        }
      } catch (err) {
        if (!disposed) setError(err instanceof Error ? err.message : 'Hub state unavailable');
      }
    }
    refresh();
    const timer = window.setInterval(refresh, POLL_MS);
    return () => {
      disposed = true;
      window.clearInterval(timer);
    };
  }, []);

  return { state, error };
}

function App() {
  const { state, error } = useHubState();
  const [mode, setMode] = useState<ClientMode>(() => routeFromHash(window.location.hash).mode ?? 'xr-headset');
  const [step, setStepState] = useState<FlowStep>(() => routeFromHash(window.location.hash).step);
  const [clientKind, setClientKind] = useState('local-hosted');

  const setStep = (next: FlowStep) => {
    setStepState(next);
    const nextHash = hashForStep(next);
    if (window.location.hash !== nextHash) {
      window.history.pushState(null, '', nextHash);
    }
  };

  useEffect(() => {
    const syncStepFromHash = () => {
      const route = routeFromHash(window.location.hash);
      setStepState(route.step);
      if (route.mode) setMode(route.mode);
    };
    window.addEventListener('hashchange', syncStepFromHash);
    return () => window.removeEventListener('hashchange', syncStepFromHash);
  }, []);

  const client = activeClient(state);
  const hasClient = Boolean(client);
  const isStreaming = Boolean(state.metrics?.streamingClients);
  const serverTarget = state.config?.serverIP && state.config?.port ? `${state.config.serverIP}:${state.config.port}` : '-';

  const stepStatus = useMemo(
    () => ({
      configure: 'current' as const,
      join: hasClient ? ('done' as const) : step === 'join' ? ('current' as const) : ('pending' as const),
      preflight: hasClient ? ('current' as const) : ('pending' as const),
      live: isStreaming ? ('done' as const) : ('pending' as const),
    }),
    [hasClient, isStreaming, step]
  );

  return (
    <Shell state={state} error={error}>
      <Stepper activeStep={step} status={stepStatus} onSelect={setStep} />
      <main className="flow-layout">
        {step === 'configure' && (
          <ConfigureStep
            state={state}
            mode={mode}
            onModeChange={setMode}
            onContinue={() => setStep(mode === 'desktop' ? 'join' : 'join')}
          />
        )}
        {step === 'join' && mode === 'desktop' && (
          <ConnectStep
            state={state}
            serverTarget={serverTarget}
            onBack={() => setStep('configure')}
            onContinue={() => setStep('preflight')}
          />
        )}
        {step === 'join' && mode !== 'desktop' && (
          <JoinStep
            state={state}
            mode={mode}
            clientKind={clientKind}
            onClientKindChange={setClientKind}
            onBack={() => setStep('configure')}
            onContinue={() => setStep('preflight')}
          />
        )}
        {step === 'preflight' && (
          <PreflightStep
            state={state}
            mode={mode}
            onBack={() => setStep('join')}
            onContinue={() => setStep('live')}
          />
        )}
        {step === 'live' && <LiveStep state={state} mode={mode} onBack={() => setStep('preflight')} />}
      </main>
    </Shell>
  );
}

const root = document.getElementById('root');
if (!root) throw new Error('Missing #root');
createRoot(root).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>
);
