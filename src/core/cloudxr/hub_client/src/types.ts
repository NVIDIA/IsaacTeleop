/*
 * SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
 * SPDX-License-Identifier: Apache-2.0
 */

export type ClientMode = 'desktop' | 'xr-headset' | 'neck-worn';
export type FlowStep = 'configure' | 'join' | 'preflight' | 'live';

export interface JoinLink {
  kind: string;
  label: string;
  href: string;
  preferred?: boolean;
  availability?: string;
}

export interface HubClient {
  clientId?: string;
  identity?: Record<string, unknown>;
  connection?: { connected?: boolean };
  stream?: { streaming?: boolean };
  capabilities?: Record<string, unknown>;
}

export interface HubState {
  updatedAt?: number;
  config?: {
    serverIP?: string;
    port?: number;
    codec?: string;
  };
  app?: {
    displayName?: string;
    status?: string;
    descriptorSource?: string;
  };
  session?: {
    displayName?: string;
    runtime?: string;
  };
  clients?: HubClient[];
  join?: {
    preferred?: string;
    links?: JoinLink[];
  };
  metrics?: {
    clientsConnected?: number;
    streamingClients?: number;
    frameRate?: number | null;
    latencyMs?: number | null;
  };
  televiz?: {
    present?: boolean;
    mode?: string;
    state?: string;
  };
}

export interface Badge {
  label: string;
  tone: 'live' | 'mock' | 'warn' | 'bad';
}
