.. SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
.. SPDX-License-Identifier: Apache-2.0

Out-of-Band Teleop Control
==========================

The **OOB (out-of-band) teleop control hub** lets you coordinate Isaac Teleop
from outside the headset — read streaming metrics, inspect connected clients,
and push configuration changes — over the **same TLS port** as the CloudXR
proxy.

The hub shares the proxy TLS port (default **48322**, override with
``PROXY_PORT``).

Quick start
-----------

**Step 1 — Start the streaming host with OOB enabled**

On first use, it is recommended to run once **without** ``--setup-oob`` to
confirm ``adb devices`` sees the headset, verify USB debugging is enabled, and
accept the self-signed certificate in the headset browser manually (both the
web client page and the ``https://<host>:48322`` proxy page). Once that
baseline works, add ``--setup-oob`` to automate the full flow.

Launch the CloudXR runtime with the ``--setup-oob`` flag (add ``--accept-eula``
on first run):

.. code-block:: bash

   python -m isaacteleop.cloudxr --accept-eula --setup-oob

This will:

1. Verify a USB-connected headset is available via ``adb devices``
2. Start the WSS proxy with the OOB control hub
3. Open the teleop page on the headset via ``adb shell am start``
4. Accept the self-signed certificate and click CONNECT automatically
   via Chrome DevTools Protocol (CDP)

You should see output confirming the hub is running:

.. code-block:: text

   CloudXR WSS proxy: running, log file: /home/<user>/.cloudxr/logs/wss.2026-04-13T202133Z.log
           oob:       enabled  (hub + USB adb automation — see OOB TELEOP block)

.. note::

   The headset must be:

   - **Connected via USB cable** for adb commands (opening the teleop URL)
   - **Connected to WiFi** on the same network as the streaming host (for web
     page access and CloudXR streaming)

   Streaming and web page access use WiFi, not USB tethering.
   ``adb forward`` is used only temporarily for CDP automation.

**Step 2 — (Manual fallback) Open the web client on the headset**

If the adb automation fails (e.g. headset not paired), you can manually open
the client URL on the headset browser with **all three** required query
parameters — ``oobEnable``, ``serverIP``, and ``port``:

.. code-block:: text

   https://nvidia.github.io/IsaacTeleop/client/?oobEnable=1&serverIP=<HOST_IP>&port=48322

Replace ``<HOST_IP>`` with the streaming host's LAN IP. The ``port`` must
match the proxy port (default 48322).

.. note::

   All three parameters are required. If ``serverIP`` or ``port`` is missing,
   the OOB control channel is silently skipped — the client will still work for
   streaming but will not register with the hub or report metrics.

**Step 3 — Verify the headset registered with the hub**

From a PC on the same network, query the hub state API (``-k`` skips the
self-signed certificate check):

.. code-block:: bash

   curl -k https://<HOST_IP>:48322/api/oob/v1/state

You should see the headset listed under ``"headsets"`` with
``"connected": true``:

.. code-block:: json

   {
     "updatedAt": 1776112022900,
     "configVersion": 0,
     "config": {"serverIP": "<HOST_IP>", "port": 48322},
     "headsets": [
       {
         "clientId": "193f3758-281e-4292-8c36-6541b58963ef",
         "connected": true,
         "deviceLabel": null,
         "registeredAt": 1776112022805,
         "metricsByCadence": {}
       }
     ]
   }

If ``"headsets"`` is empty, double-check that the URL on the headset includes
both ``serverIP`` and ``port`` and that the headset can reach the host over the
network.

**Step 4 — (Optional) Push config to the headset**

Before or after the headset connects to the CloudXR stream, you can push
configuration overrides via the HTTP config API:

.. code-block:: bash

   curl -k "https://<HOST_IP>:48322/api/oob/v1/config?serverIP=<HOST_IP>&port=48322&codec=av1"

See ``GET /api/oob/v1/config`` below for all supported keys.

**Step 5 — Stream and poll for metrics**

With ``--setup-oob``, CONNECT is clicked automatically via CDP.  If running
without it, press **CONNECT** on the headset manually.  Once streaming begins,
the headset reports metrics to the hub every 500 ms.  Poll the state endpoint
from a PC to collect them:

.. code-block:: bash

   # Poll every 2 seconds (adjust to taste)
   watch -n 2 'curl -sk https://<HOST_IP>:48322/api/oob/v1/state | python3 -m json.tool'

The ``metricsByCadence`` field on each headset entry will now contain live streaming metrics.

ADB automation
--------------

The ``--setup-oob`` flag automates headset setup via USB ``adb``:

1. **adb devices** verifies exactly one device is connected
2. **am start** opens the teleop bookmark URL in the headset browser with
   the correct ``oobEnable=1``, ``serverIP``, and ``port`` parameters
3. **CDP connect** forwards the browser's DevTools socket over ``adb``,
   accepts the self-signed certificate interstitial, and clicks CONNECT
   via Chrome DevTools Protocol (``Input.dispatchMouseEvent``)

Streaming and web page access use WiFi, not USB tethering.  The headset
reaches the streaming host directly over WiFi.  ``adb forward`` is used only
temporarily during CDP automation to reach the browser's DevTools socket.

Prerequisites:

- ``adb`` must be on ``PATH`` (Android SDK Platform Tools)
- The headset must be connected via USB with USB debugging enabled
- The headset must be on the same WiFi network as the streaming host

If any step fails, the hub still starts.  Fall back to
``chrome://inspect/#devices`` from the PC or tap CONNECT on the headset
directly.

Architecture
------------

.. list-table::
   :header-rows: 1
   :widths: 22 38 40

   * - Role
     - Software
     - What it does
   * - **XR headset**
     - Isaac Teleop WebXR client in the device browser
     - Registers with the hub via WebSocket, reports streaming metrics
       periodically (default every 500 ms), receives config pushes.
   * - **Streaming host**
     - ``python -m isaacteleop.cloudxr --setup-oob``
     - Runs CloudXR runtime + WSS proxy + OOB hub on a single TLS port.
       Opens the teleop page and clicks CONNECT via USB adb + CDP.
   * - **Operator / scripts**
     - ``curl``, browser, or custom tooling
     - Reads state via HTTP, optionally pushes config via HTTP.

WebSocket protocol
------------------

Endpoint: ``wss://<host>:<port>/oob/v1/ws``

All messages are JSON text frames with ``{"type": ..., "payload": ...}``.

Registration (first message)
^^^^^^^^^^^^^^^^^^^^^^^^^^^^

.. code-block:: json

   {
     "type": "register",
     "payload": {
       "role": "headset",
       "deviceLabel": "Quest 3",
       "token": "<optional CONTROL_TOKEN>"
     }
   }

``role`` must be ``"headset"``. The hub replies with:

.. code-block:: json

   {
     "type": "hello",
     "payload": {
       "clientId": "<uuid>",
       "configVersion": 0,
       "config": {"serverIP": "...", "port": 48322}
     }
   }

Headset → hub: ``clientMetrics``
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

.. code-block:: json

   {
     "type": "clientMetrics",
     "payload": {
       "t": 1712800000000,
       "cadence": "frame",
       "metrics": {
         "streaming.framerate": 72.0,
         "render.pose_to_render_time": 18.5
       }
     }
   }

HTTP API
--------

All endpoints use **GET** with query parameters on the proxy TLS port.

``GET /api/oob/v1/state``
^^^^^^^^^^^^^^^^^^^^^^^^^

Returns the current hub state: connected headsets, latest metrics, and config
version.

.. code-block:: bash

   curl -k https://localhost:48322/api/oob/v1/state

Example response:

.. code-block:: json

   {
     "updatedAt": 1712800000000,
     "configVersion": 0,
     "config": {"serverIP": "10.0.0.1", "port": 48322},
     "headsets": [
       {
         "clientId": "abc-123",
         "connected": true,
         "deviceLabel": "Quest 3",
         "registeredAt": 1712799990000,
         "metricsByCadence": {
           "frame": {
             "at": 1712800000000,
             "metrics": {"streaming.framerate": 72.0}
           }
         }
       }
     ]
   }

``GET /api/oob/v1/config``
^^^^^^^^^^^^^^^^^^^^^^^^^^

Push config to connected headsets via query parameters:

.. code-block:: bash

   curl -k "https://localhost:48322/api/oob/v1/config?serverIP=10.0.0.5&port=48322"

Example response:

.. code-block:: json

   {
     "ok": true,
     "changed": true,
     "configVersion": 1,
     "targetCount": 1
   }

Supported query keys: ``serverIP``, ``port``, ``panelHiddenAtStart``, ``codec``.
Optional ``targetClientId`` restricts the push to a single headset (returns 404
if not connected).

Authentication
--------------

Set ``CONTROL_TOKEN=<secret>`` to require a token on all hub operations.
Pass it as:

- WebSocket: ``"token"`` field in the ``register`` payload
- HTTP: ``?token=<secret>`` query parameter or ``X-Control-Token`` header

Web client integration
----------------------

The WebXR client connects to the hub when the page URL contains
``oobEnable=1`` plus ``serverIP`` and ``port``:

.. code-block:: text

   https://nvidia.github.io/IsaacTeleop/client/?oobEnable=1&serverIP=10.0.0.1&port=48322

The client builds ``wss://{serverIP}:{port}/oob/v1/ws`` and:

1. Registers as role ``"headset"``
2. Reports ``clientMetrics`` periodically (default every 500 ms)
3. Receives ``config`` pushes from operator

URL query parameter overrides
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

The following URL parameters override their corresponding form fields (and
``localStorage`` values) so that bookmarked links always take priority over
previously saved settings:

- ``serverIP`` CloudXR server IP address
- ``port`` CloudXR server port
- ``codec`` video codec
- ``panelHiddenAtStart`` hide the control panel on load

Environment variables
---------------------

.. list-table::
   :header-rows: 1
   :widths: 30 70

   * - Variable
     - Description
   * - ``PROXY_PORT``
     - WSS proxy port (default ``48322``)
   * - ``CONTROL_TOKEN``
     - Optional auth token for hub access
   * - ``TELEOP_STREAM_SERVER_IP``
     - Override the auto-detected LAN IP in hub initial config
   * - ``TELEOP_PROXY_HOST``
     - Override the LAN IP used for headset bookmark URLs
   * - ``TELEOP_WEB_CLIENT_BASE``
     - Override the WebXR client origin URL
   * - ``TELEOP_STREAM_PORT``
     - Override the signaling port (default same as proxy port)
   * - ``TELEOP_CLIENT_CODEC``
     - Default video codec for headset bookmarks
   * - ``TELEOP_CLIENT_PANEL_HIDDEN_AT_START``
     - Hide control panel on load (``true`` / ``false``)
