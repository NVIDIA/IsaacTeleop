/*
 * SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
 * SPDX-License-Identifier: Apache-2.0
 */

/**
 * HeadsetControlChannel — WebSocket client that connects the XR headset to the
 * teleop control hub running in the WSS proxy.
 *
 * Protocol: docs/source/references/teleop_control_protocol.rst (Sphinx build)
 * Hub WS URL: wss://<host>:<PROXY_PORT>/teleop/v1/ws
 *
 * Usage (in App.tsx):
 *
 *   const channel = new HeadsetControlChannel({
 *     url: 'wss://host:48322/teleop/v1/ws',
 *     onSessionCommand: (action) => { ... },
 *     onConfig: (config, version) => { ... },
 *     getMetricsSnapshot: () => [ { cadence: 'frame', metrics: { ... } } ],
 *   });
 *   channel.connect();
 *   // on cleanup:
 *   channel.dispose();
 */

/** Stream target fields the hub may push to the headset. */
export interface StreamConfig {
  serverIP?: string;
  port?: number;
  proxyUrl?: string | null;
  mediaAddress?: string;
  mediaPort?: number;
}

export type SessionAction = 'connect' | 'disconnect';

export interface MetricsSnapshot {
  cadence: string;
  metrics: Record<string, number>;
}

export interface ControlChannelOptions {
  /** Full WSS URL of the hub, e.g. wss://host:48322/teleop/v1/ws */
  url: string;
  /** Sent in the register message. Must match CONTROL_TOKEN env var if set. */
  token?: string;
  /** Human-readable label shown in the operator dashboard. */
  deviceLabel?: string;
  /** Called when the hub sends a sessionCommand (connect or disconnect). */
  onSessionCommand: (action: SessionAction, requestId?: string) => void;
  /**
   * Called on hello (initial config) and on config push.
   * Apply the config to the CloudXR connection settings before connect.
   */
  onConfig: (config: StreamConfig, configVersion: number) => void;
  /** Called when the WebSocket connection state changes. */
  onConnectionChange?: (connected: boolean) => void;
  /**
   * Optional: called periodically to get the latest metrics to report.
   * Return an empty array or null/undefined to skip a tick.
   */
  getMetricsSnapshot?: () => MetricsSnapshot[] | null | undefined;
  /** How often to report metrics (ms). Default: 500. */
  metricsIntervalMs?: number;
}

const RECONNECT_DELAY_MS = 3000;
const DEFAULT_METRICS_INTERVAL_MS = 500;

export class HeadsetControlChannel {
  private ws: WebSocket | null = null;
  private disposed = false;
  private metricsTimer: ReturnType<typeof setInterval> | null = null;
  private reconnectTimer: ReturnType<typeof setTimeout> | null = null;

  constructor(private readonly opts: ControlChannelOptions) {}

  /** Open the WebSocket and start the reconnection loop. */
  connect(): void {
    if (this.disposed) return;
    this._openWebSocket();
  }

  /** Close the channel permanently. Safe to call multiple times. */
  dispose(): void {
    this.disposed = true;
    this._clearTimers();
    if (this.ws) {
      this.ws.onclose = null; // prevent reconnect on this close
      this.ws.close();
      this.ws = null;
    }
  }

  // ---------------------------------------------------------------------------
  // Private
  // ---------------------------------------------------------------------------

  private _openWebSocket(): void {
    if (this.disposed) return;

    let ws: WebSocket;
    try {
      ws = new WebSocket(this.opts.url);
    } catch (err) {
      if (this.disposed) return;
      console.warn(
        '[ControlChannel] WebSocket constructor failed for',
        this.opts.url,
        err
      );
      this.ws = null;
      this._afterSocketClosed();
      return;
    }

    this.ws = ws;

    ws.onopen = () => {
      ws.send(
        JSON.stringify({
          type: 'register',
          payload: {
            role: 'headset',
            ...(this.opts.token ? { token: this.opts.token } : {}),
            ...(this.opts.deviceLabel ? { deviceLabel: this.opts.deviceLabel } : {}),
          },
        })
      );
      this.opts.onConnectionChange?.(true);
      this._startMetricsTimer();
    };

    ws.onmessage = (ev) => {
      if (typeof ev.data !== 'string') return;
      let msg: { type?: string; payload?: unknown };
      try {
        msg = JSON.parse(ev.data);
      } catch {
        return;
      }
      this._handleMessage(msg);
    };

    ws.onclose = () => {
      this.ws = null;
      this._afterSocketClosed();
    };

    ws.onerror = () => {
      // onclose fires next; reconnect logic lives there
    };
  }

  /** Clear timers, notify disconnected, schedule reconnect (same path as WebSocket onclose). */
  private _afterSocketClosed(): void {
    this._clearTimers();
    this.opts.onConnectionChange?.(false);
    if (!this.disposed) {
      this.reconnectTimer = setTimeout(() => this._openWebSocket(), RECONNECT_DELAY_MS);
    }
  }

  private _handleMessage(msg: { type?: string; payload?: unknown }): void {
    const type = msg.type;
    const payload = (msg.payload ?? {}) as Record<string, unknown>;

    if (type === 'hello') {
      // hello to headset includes initial config
      if (
        payload.config != null &&
        typeof payload.configVersion === 'number'
      ) {
        this.opts.onConfig(payload.config as StreamConfig, payload.configVersion as number);
      }
    } else if (type === 'config') {
      if (
        payload.config != null &&
        typeof payload.configVersion === 'number'
      ) {
        this.opts.onConfig(payload.config as StreamConfig, payload.configVersion as number);
      }
    } else if (type === 'sessionCommand') {
      const action = payload.action;
      if (action === 'connect' || action === 'disconnect') {
        const requestId =
          typeof payload.requestId === 'string' ? payload.requestId : undefined;
        this.opts.onSessionCommand(action, requestId);
      }
    } else if (type === 'error') {
      console.warn('[ControlChannel] Hub error:', payload);
    }
  }

  private _startMetricsTimer(): void {
    if (!this.opts.getMetricsSnapshot) return;
    const interval = this.opts.metricsIntervalMs ?? DEFAULT_METRICS_INTERVAL_MS;
    this.metricsTimer = setInterval(() => {
      if (!this.ws || this.ws.readyState !== WebSocket.OPEN) return;
      const snapshots = this.opts.getMetricsSnapshot?.();
      if (!snapshots || snapshots.length === 0) return;
      const t = Date.now();
      for (const { cadence, metrics } of snapshots) {
        if (Object.keys(metrics).length === 0) continue;
        this.ws.send(
          JSON.stringify({
            type: 'clientMetrics',
            payload: { t, cadence, metrics },
          })
        );
      }
    }, interval);
  }

  private _clearTimers(): void {
    if (this.metricsTimer !== null) {
      clearInterval(this.metricsTimer);
      this.metricsTimer = null;
    }
    if (this.reconnectTimer !== null) {
      clearTimeout(this.reconnectTimer);
      this.reconnectTimer = null;
    }
  }
}
