/*
 * SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
 * SPDX-License-Identifier: Apache-2.0
 */

import type { HubState, JoinLink } from './types';

export async function fetchHubState(): Promise<HubState> {
  const url = new URL('/api/oob/v1/state', window.location.href);
  const token = new URLSearchParams(window.location.search).get('token');
  if (token) url.searchParams.set('token', token);
  const response = await fetch(url, { cache: 'no-store' });
  if (!response.ok) {
    throw new Error(`Hub state unavailable: HTTP ${response.status}`);
  }
  return (await response.json()) as HubState;
}

export function bestJoinLink(state: HubState, kind?: string) {
  const links = state.join?.links ?? [];
  return links.find(link => link.kind === kind && link.href) ?? links.find(link => link.preferred) ?? links[0];
}

function currentHref() {
  return typeof window === 'undefined' ? undefined : window.location.href;
}

function isLocalViteDevOrigin(url: URL) {
  return url.port === '5173' && (url.hostname === 'localhost' || url.hostname === '127.0.0.1');
}

export function hostedClientHrefForHub(link: JoinLink, hubHref = currentHref()) {
  if (link.kind !== 'local-hosted' || !hubHref) return link.href;
  const hubUrl = new URL(hubHref);
  if (isLocalViteDevOrigin(hubUrl)) return link.href;

  const original = new URL(link.href, hubUrl);
  const hosted = new URL('/client/', hubUrl.origin);
  hosted.search = original.search;
  return hosted.toString();
}

export function bestJoinLinkForHub(state: HubState, kind?: string, hubHref = currentHref()) {
  const link = bestJoinLink(state, kind);
  if (!link) return undefined;
  return { ...link, href: hostedClientHrefForHub(link, hubHref) };
}

export function activeClient(state: HubState) {
  const clients = state.clients ?? [];
  return clients.find(client => client.stream?.streaming) ?? clients[0] ?? null;
}

export function valueText(value: unknown, fallback = '-') {
  if (value === undefined || value === null || value === '') return fallback;
  return String(value);
}
