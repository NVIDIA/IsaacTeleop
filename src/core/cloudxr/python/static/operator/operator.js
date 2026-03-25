/*
 * SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
 * SPDX-License-Identifier: Apache-2.0
 */

/**
 * Isaac Teleop — Operator Dashboard (vanilla JS client).
 *
 * Connects to the hub as a "dashboard" role via WebSocket, polls the snapshot
 * API every second for state updates, and provides controls to set the stream
 * target (serverIP/port) and send connect/disconnect commands to headsets.
 */
(function () {
  'use strict';

  // ---------------------------------------------------------------------------
  // Config: derive hub URL from current page origin
  // ---------------------------------------------------------------------------
  const params = new URLSearchParams(window.location.search);
  const TOKEN = params.get('token') || '';
  const WS_URL =
    params.get('wsUrl') ||
    `wss://${window.location.host}/teleop/v1/ws`;
  const STATE_URL = `https://${window.location.host}/api/teleop/v1/state`;

  function fillConnectionInstructions() {
    const hubEl = document.getElementById('instrHubWs');
    if (hubEl) hubEl.textContent = WS_URL;
    const headsetEl = document.getElementById('instrHeadsetParams');
    if (headsetEl) {
      const p = new URLSearchParams();
      p.set('controlWsUrl', WS_URL);
      if (TOKEN) p.set('controlToken', TOKEN);
      headsetEl.textContent =
        'https://<your-teleop-web-client-url>/' +
        (p.toString() ? '?' + p.toString() : '');
    }
  }

  const POLL_INTERVAL_MS = 1000;
  const RECONNECT_DELAY_MS = 3000;

  // ---------------------------------------------------------------------------
  // State
  // ---------------------------------------------------------------------------
  let ws = null;
  let wsConnected = false;
  let selectedHeadsetId = null;    // client ID of headset currently highlighted
  let snapshot = null;             // latest GET /api/teleop/v1/state response
  let pollTimer = null;
  let reconnectTimer = null;

  // ---------------------------------------------------------------------------
  // DOM refs
  // ---------------------------------------------------------------------------
  const statusDot = document.getElementById('statusDot');
  const statusLabel = document.getElementById('statusLabel');
  const headsetSelect = document.getElementById('headsetSelect');
  const serverIPInput = document.getElementById('serverIP');
  const portInput = document.getElementById('port');
  const proxyUrlInput = document.getElementById('proxyUrl');
  const btnSetConfig = document.getElementById('btnSetConfig');
  const btnConnect = document.getElementById('btnConnect');
  const btnDisconnect = document.getElementById('btnDisconnect');
  const configVersionEl = document.getElementById('configVersion');
  const headsetListEl = document.getElementById('headsetList');
  const metricsPanelEl = document.getElementById('metricsPanel');
  const toastEl = document.getElementById('toast');

  // ---------------------------------------------------------------------------
  // Toast
  // ---------------------------------------------------------------------------
  let toastTimer = null;
  function showToast(msg, isError) {
    if (toastTimer) clearTimeout(toastTimer);
    toastEl.textContent = msg;
    toastEl.className = 'toast show' + (isError ? ' error' : '');
    toastTimer = setTimeout(() => {
      toastEl.classList.remove('show');
    }, 3500);
  }

  async function copyTextToClipboard(text) {
    try {
      if (navigator.clipboard?.writeText) {
        await navigator.clipboard.writeText(text);
        return true;
      }
    } catch (_) { /* fall through */ }
    try {
      const ta = document.createElement('textarea');
      ta.value = text;
      ta.setAttribute('readonly', '');
      ta.style.position = 'fixed';
      ta.style.left = '-9999px';
      document.body.appendChild(ta);
      ta.select();
      const ok = document.execCommand('copy');
      document.body.removeChild(ta);
      return ok;
    } catch (_) {
      return false;
    }
  }

  function setupHubWsClickToCopy() {
    const hubEl = document.getElementById('instrHubWs');
    if (!hubEl) return;

    async function onCopy(ev) {
      ev.preventDefault();
      const ok = await copyTextToClipboard(WS_URL);
      if (ok) showToast('Hub WebSocket URL copied');
      else showToast('Copy failed — select and copy manually', true);
    }

    hubEl.title = 'Click to copy hub WebSocket URL';
    hubEl.addEventListener('click', onCopy);
    hubEl.addEventListener('keydown', (e) => {
      if (e.key === 'Enter' || e.key === ' ') onCopy(e);
    });
  }

  // ---------------------------------------------------------------------------
  // WebSocket connection
  // ---------------------------------------------------------------------------
  function openWS() {
    if (ws) return;
    ws = new WebSocket(WS_URL);

    ws.onopen = () => {
      wsConnected = true;
      setStatusConnected(true);
      ws.send(JSON.stringify({
        type: 'register',
        payload: {
          role: 'dashboard',
          ...(TOKEN ? { token: TOKEN } : {}),
        },
      }));
      startPolling();
    };

    ws.onmessage = (ev) => {
      let msg;
      try { msg = JSON.parse(ev.data); } catch { return; }
      handleServerMessage(msg);
    };

    ws.onclose = () => {
      wsConnected = false;
      ws = null;
      setStatusConnected(false);
      stopPolling();
      reconnectTimer = setTimeout(openWS, RECONNECT_DELAY_MS);
    };

    ws.onerror = () => { /* onclose fires next */ };
  }

  function send(type, payload) {
    if (!ws || ws.readyState !== WebSocket.OPEN) {
      showToast('Not connected to hub', true);
      return;
    }
    ws.send(JSON.stringify({ type, payload }));
  }

  function handleServerMessage(msg) {
    const type = msg.type;
    const payload = msg.payload || {};

    if (type === 'hello') {
      // Our own clientId — nothing to display
    } else if (type === 'error') {
      showToast(`Hub error [${payload.code}]: ${payload.message}`, true);
    }
  }

  // ---------------------------------------------------------------------------
  // Status UI
  // ---------------------------------------------------------------------------
  function setStatusConnected(connected) {
    statusDot.className = 'status-dot' + (connected ? ' connected' : '');
    statusLabel.textContent = connected
      ? 'Connected to teleop hub'
      : 'Not connected to teleop hub';
    statusLabel.title = connected
      ? 'This tab is registered with the teleop control hub as an operator (dashboard). Headset status is shown below.'
      : 'No WebSocket to the hub, or reconnecting. Commands and live headset list need this link.';
  }

  // ---------------------------------------------------------------------------
  // Polling
  // ---------------------------------------------------------------------------
  function startPolling() {
    stopPolling();
    poll();
    pollTimer = setInterval(poll, POLL_INTERVAL_MS);
  }

  function stopPolling() {
    if (pollTimer) { clearInterval(pollTimer); pollTimer = null; }
  }

  async function poll() {
    try {
      const url = TOKEN
        ? `${STATE_URL}?token=${encodeURIComponent(TOKEN)}`
        : STATE_URL;
      const res = await fetch(url);
      if (!res.ok) {
        if (res.status === 401) showToast('State API: Unauthorized — check token', true);
        return;
      }
      snapshot = await res.json();
      renderSnapshot(snapshot);
    } catch {
      // Network error — hub probably restarting; WS reconnect handles it
    }
  }

  // ---------------------------------------------------------------------------
  // Rendering
  // ---------------------------------------------------------------------------
  function updateHeadsetDependentButtons() {
    const hasHeadsets =
      snapshot &&
      snapshot.headsets &&
      snapshot.headsets.length > 0;
    const selected = Boolean(headsetSelect.value);
    const enabled = hasHeadsets && selected;
    btnSetConfig.disabled = !enabled;
    btnConnect.disabled = !enabled;
    btnDisconnect.disabled = !enabled;
  }

  function renderSnapshot(data) {
    // Config version
    configVersionEl.textContent = data.configVersion
      ? `Config version: ${data.configVersion}`
      : '';

    // Populate config fields if empty (initial load)
    if (data.config && data.config.serverIP && !serverIPInput.value) {
      serverIPInput.value = data.config.serverIP || '';
      portInput.value = data.config.port != null ? data.config.port : '';
      proxyUrlInput.value = data.config.proxyUrl || '';
    }

    // Headset select dropdown
    const prevSelectValue = headsetSelect.value;
    while (headsetSelect.options.length > 1) headsetSelect.remove(1);
    (data.headsets || []).forEach(h => {
      const opt = document.createElement('option');
      opt.value = h.clientId;
      opt.textContent = h.deviceLabel || h.clientId.slice(0, 8);
      headsetSelect.appendChild(opt);
    });
    if (
      prevSelectValue &&
      [...headsetSelect.options].some(o => o.value === prevSelectValue)
    ) {
      headsetSelect.value = prevSelectValue;
    } else {
      headsetSelect.value = '';
    }
    if (!data.headsets || data.headsets.length === 0) {
      headsetSelect.value = '';
    } else if (
      headsetSelect.value &&
      !data.headsets.some(h => h.clientId === headsetSelect.value)
    ) {
      headsetSelect.value = '';
    }
    selectedHeadsetId = headsetSelect.value || null;

    // Headset cards
    if (!data.headsets || data.headsets.length === 0) {
      headsetListEl.innerHTML = '<div class="empty">No headsets connected</div>';
    } else {
      headsetListEl.innerHTML = '';
      data.headsets.forEach(h => {
        const card = document.createElement('div');
        card.className = 'headset-card' + (h.clientId === selectedHeadsetId ? ' selected' : '');
        const dot = h.connected ? '🟢' : '🔴';
        card.innerHTML = `
          <div class="headset-name">${dot} ${escHtml(h.deviceLabel || 'Headset')}</div>
          <div class="headset-id">${h.clientId}</div>
        `;
        card.addEventListener('click', () => {
          selectedHeadsetId = h.clientId;
          headsetSelect.value = h.clientId;
          renderSnapshot(snapshot);
        });
        headsetListEl.appendChild(card);
      });
    }

    // Metrics for selected headset
    const selId = headsetSelect.value || null;
    const headset = selId
      ? (data.headsets || []).find(h => h.clientId === selId)
      : null;
    renderMetrics(headset);
    updateHeadsetDependentButtons();
  }

  function renderMetrics(headset) {
    metricsPanelEl.replaceChildren();

    if (!headset) {
      const empty = document.createElement('div');
      empty.className = 'empty';
      empty.textContent = 'Select a headset to see metrics';
      metricsPanelEl.appendChild(empty);
      return;
    }

    const byC = headset.metricsByCadence || {};
    const grid = document.createElement('div');
    grid.className = 'metrics-grid';

    Object.entries(byC).forEach(([, entry]) => {
      const metrics = entry.metrics || {};
      Object.entries(metrics).forEach(([key, val]) => {
        const display = formatMetric(key, val);
        const tile = document.createElement('div');
        tile.className = 'metric-tile';
        const valueEl = document.createElement('div');
        valueEl.className = 'metric-value';
        valueEl.textContent = display.value;
        const nameEl = document.createElement('div');
        nameEl.className = 'metric-name';
        nameEl.textContent = display.label;
        tile.appendChild(valueEl);
        tile.appendChild(nameEl);
        grid.appendChild(tile);
      });
    });

    if (grid.childElementCount === 0) {
      const empty = document.createElement('div');
      empty.className = 'empty';
      empty.textContent = 'No metrics received yet';
      metricsPanelEl.appendChild(empty);
    } else {
      metricsPanelEl.appendChild(grid);
    }
  }

  /** Human labels for CloudXR MetricsName wire strings (see @nvidia/cloudxr Session). */
  var METRIC_LABELS = {
    'render.framerate': 'Render FPS',
    'streaming.framerate': 'Streaming FPS',
    'render.pose_to_render_time': 'Pose → render (ms)',
  };

  function humanizeMetricKey(key) {
    if (METRIC_LABELS[key]) return METRIC_LABELS[key];
    return key.split('.').map(function (segment) {
      return segment.split('_').map(function (word) {
        return word.charAt(0).toUpperCase() + word.slice(1);
      }).join(' ');
    }).join(' · ');
  }

  function formatMetric(key, val) {
    const num = typeof val === 'number' ? val : parseFloat(val);
    const rounded = Number.isFinite(num) ? num.toFixed(1) : '—';
    const label = humanizeMetricKey(String(key));
    return { value: rounded, label };
  }

  function escHtml(s) {
    return String(s)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;');
  }

  // ---------------------------------------------------------------------------
  // User actions
  // ---------------------------------------------------------------------------
  btnSetConfig.addEventListener('click', () => {
    if (btnSetConfig.disabled) return;
    const targetId = headsetSelect.value;
    if (!targetId) {
      showToast('Select a headset first', true);
      return;
    }
    const serverIP = serverIPInput.value.trim();
    const port = parseInt(portInput.value, 10);
    const proxyUrl = proxyUrlInput.value.trim() || null;

    if (!serverIP) { showToast('Server IP is required', true); return; }
    if (!Number.isFinite(port) || port < 1 || port > 65535) {
      showToast('Port must be 1–65535', true);
      return;
    }

    const config = { serverIP, port };
    if (proxyUrl) config.proxyUrl = proxyUrl;

    const payload = { config, targetClientId: targetId };
    if (TOKEN) payload.token = TOKEN;

    send('setConfig', payload);
    showToast('Config applied');
  });

  function sendConnectCommand() {
    if (btnConnect.disabled) return;
    const payload = { action: 'connect' };
    if (TOKEN) payload.token = TOKEN;
    payload.targetClientId = headsetSelect.value;
    send('command', payload);
    showToast('Connect command sent');
  }

  function sendDisconnectCommand() {
    if (btnDisconnect.disabled) return;
    const payload = { action: 'disconnect' };
    if (TOKEN) payload.token = TOKEN;
    payload.targetClientId = headsetSelect.value;
    send('command', payload);
    showToast('Disconnect command sent');
  }

  btnConnect.addEventListener('click', sendConnectCommand);
  btnDisconnect.addEventListener('click', sendDisconnectCommand);

  document.addEventListener('keydown', (e) => {
    if (e.repeat) return;
    if (e.ctrlKey || e.metaKey || e.altKey) return;
    const t = e.target;
    if (t instanceof HTMLElement) {
      if (t.isContentEditable) return;
      const tag = t.tagName;
      if (tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT') return;
    }
    if (e.code === 'KeyC') {
      if (btnConnect.disabled) return;
      e.preventDefault();
      sendConnectCommand();
    } else if (e.code === 'KeyD') {
      if (btnDisconnect.disabled) return;
      e.preventDefault();
      sendDisconnectCommand();
    }
  });

  headsetSelect.addEventListener('change', () => {
    if (snapshot) renderSnapshot(snapshot);
  });

  // ---------------------------------------------------------------------------
  // Boot
  // ---------------------------------------------------------------------------
  fillConnectionInstructions();
  setupHubWsClickToCopy();
  updateHeadsetDependentButtons();
  setStatusConnected(false);
  openWS();
})();
