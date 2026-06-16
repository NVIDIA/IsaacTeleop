/*
 * SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
 * SPDX-License-Identifier: Apache-2.0
 */

import React, { type ReactNode } from 'react';

import type { HubState } from '../types';
import { Badge } from './Badge';

interface ShellProps {
  state: HubState;
  error: string | null;
  children: ReactNode;
}

export function Shell({ state, error, children }: ShellProps) {
  const connected = !error;
  const appName = state.app?.displayName ?? 'Isaac Teleop';
  const server = state.config?.serverIP ?? 'waiting for server';

  return (
    <div className="app-shell">
      <header className="topbar">
        <div className="brand">
          <strong>NVIDIA</strong>
          <span>Isaac</span>
          <b>Teleop Hub</b>
          <Badge label="Prototype" tone="mock" />
        </div>
        <div className="topbar-status">
          <span className={`status-dot ${connected ? 'status-live' : 'status-bad'}`} />
          <span>{connected ? `connected · ${server} · ${appName}` : error}</span>
        </div>
      </header>
      {children}
    </div>
  );
}
