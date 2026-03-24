.. SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
.. SPDX-License-Identifier: Apache-2.0

Out-of-band teleop control
==========================

This guide explains how to **coordinate Isaac Teleop from outside the headset**—change where the headset
streams from, read status, and (for advanced setups) push settings over HTTP—using the same TLS port as
the CloudXR proxy when you enable the feature.

**Primary audience:** **operators** setting up a lab or demo. **Integrators** (automation, custom
dashboards, metrics) should read :ref:`teleop-oob-integrators` after the operator workflow.

**Supported browsers and devices:** Use an **Android-based XR headset** with a **Chromium-based** browser
for WebXR. On the **PC**, use a **Chromium-based** browser for **remote inspect**—for example
**``chrome://inspect``** in Google Chrome or **``edge://inspect``** in Microsoft Edge. Other browsers or
non-Android XR stacks are outside the scope of this guide.

**Supported operator flow:** start with **``--setup-oob``** so the bookmark opens on the headset → on
the **PC**, open **remote inspect** on that tab → click **CONNECT** in DevTools (WebXR user gesture).
There is **no** ``autoConnect`` query flag and no hub-driven session start.

**What this is not:** it does not replace CloudXR streaming. Video, audio, and poses still use the
normal streaming path. The **control plane** (this document) coordinates **which server** the headset should use; the usual
**when to connect** path is the in-page **CONNECT** control (or refresh / disconnect in the UI), not
an HTTP trigger. **Signaling is TLS:** use **``https://``** for HTTP on the proxy port and **``wss://``**
for OOB WebSocket and CloudXR signaling through this stack—there is no supported operator path to use
plain **``http``** / **``ws``** here.

**What you get when it is enabled**

* A **WebXR page** on the headset talks to a small **control service** (the “hub”) over WSS.
* From a **PC** (optional for operators), you can call **HTTPS** on the proxy port to **read state** and
  **update streaming settings** (``/api/oob/v1/state`` and ``/api/oob/v1/config``), or use WebSocket
  **``setConfig``** from a **``dashboard``** client. **Connect** / **disconnect** are driven from the
  **WebXR page** while you control it through DevTools (remote inspect), not from the hub—see
  :ref:`teleop-user-activation`.
* Optional **``--setup-oob``** automates **adb**: open the right URL on the device and wire USB or
  wireless debugging so you rarely type long URLs on the headset.

The proxy’s HTTP API uses **GET** with query parameters because the WebSocket stack on this port only
accepts GET for ordinary HTTP. **``curl``** and scripts work fine for **state** and **config**.

.. _teleop-roles-three-machines:

Who is involved
---------------

Most setups look like **three roles** (they can be the same physical machine):

.. list-table::
   :header-rows: 1
   :widths: 22 38 40

   * - Role
     - Typical software
     - What it does
   * - **XR headset**
     - Isaac Teleop **WebXR client** in the device browser
     - Runs the immersive session and streaming client. Registers with the hub, applies the
       streaming **host/port** from **``hello``** / **``config``**, and starts/stops the XR session
       from the **in-page** controls only.
   * - **Operator machine**
     - Your PC: Chromium **remote inspect**; optionally **``curl``** or scripts against **HTTPS**
     - Drives **CONNECT** through the inspected Teleop tab; can change streaming target via HTTP
       **config** or WebSocket **``setConfig``** (integrator-style). There is **no** built-in browser
       dashboard and **no** hub API to start/stop the XR session remotely.
   * - **Streaming host**
     - Machine where **``python -m isaacteleop.cloudxr``** runs (CloudXR runtime + TLS proxy)
     - Listens on the **proxy TLS port** (default **48322**). Serves CloudXR signaling and, if you
       enable it, the teleop hub. The **``serverIP``** / **``port``** you configure name **this**
       streaming endpoint—the headset must be able to reach that address on the network.

The headset must reach **both** the **WebXR page** (often ``https://…:8080/`` during development)
**and** the **OOB WebSocket** on the streaming host. The bookmark adds **``oobEnable=1``** plus the same
**``serverIP``** and **``port``** as CloudXR signaling; the client opens **only** that
``wss://{serverIP}:{port}/oob/v1/ws`` (see :ref:`teleop-headset-control-url`). There is no implicit
default to the page origin.

**Same PC as the headset cable?** Very often the streaming host and the PC you type on are one
computer. The split above still helps: the **WebXR tab** and **your terminal** are different
programs.

End-to-end workflow (the usual path)
------------------------------------

With **``--setup-oob``**, the terminal prints an **OOB TELEOP** banner that mirrors the three steps
below (same order and links).

**Prerequisites:** **``adb``** on PATH; USB or wireless debugging; **one** device in **``adb devices``**;
WebXR dev server reachable at **``https://127.0.0.1:8080/``** (USB) or **``https://<PC-LAN>:8080/``**
(wireless), with a certificate the headset trusts.

**1 — Start with hub + adb automation**

.. code-block:: bash

   python -m isaacteleop.cloudxr --setup-oob tethered

Wireless: use **``--setup-oob <HOST>:5555``** instead. Add **``--wss-only``** if you skip the CloudXR
runtime (see :ref:`teleop-wss-only-testing`).

Wait for **``WSS proxy listening on port …``**; the bookmark is printed in the **OOB TELEOP** banner.
**``--setup-oob``** runs **``am start``** so the page opens on the headset (or open the URL yourself if
you omitted the flag).

**2 — Inspect from the PC**

On the **PC**, open your Chromium browser to **``chrome://inspect/#devices``** (Chrome) or
**``edge://inspect``** (Edge). Under **Remote Target**, select the headset browser tab that shows
**Isaac Teleop Web Client** (or the matching URL) and click **inspect**.

**3 — CONNECT (required gesture)**

In the DevTools window for that page, click **CONNECT** on the Teleop UI (same as tapping CONNECT on
the headset). WebXR needs this user gesture; see :ref:`teleop-user-activation`.

**4 — Disconnect (from the PC)**

To end the session without reaching for the headset, keep the **same** DevTools window focused on the
Teleop page and **reload** it—for example click the **URL** in the inspector’s address bar and press
**Enter**, or use the refresh action. That tears down the page session the same way as navigating away
on the device.

**After that (optional):** change streaming target with **``GET /api/oob/v1/config``** or WebSocket
**``setConfig``** without rebuilding the bookmark URL (see :ref:`teleop-stream-defaults`).

.. _teleop-setup-oob-cli:

Choosing ``--setup-oob`` and when the hub is on
------------------------------------------------

**Omit** **``--setup-oob``** if you will open the teleop URL yourself and do not need adb help. In
that case the **OOB HTTP** paths return **404**, and **``/oob/v1/ws``** is forwarded to the CloudXR
runtime instead of the hub—so teleop control expects the **full** stack, not **``--wss-only``**
alone.

**``--setup-oob tethered``** — USB. After the proxy is listening, the tool:

1. Starts a **PC-side UDP-over-TCP relay** on TCP port **47999** (override with **``TELEOP_UDP_RELAY_PORT``**).
2. Sets up **``adb reverse``** for the proxy port (**48322**), the WebXR dev-server port (**8080**), and the
   relay TCP port (**47999**).
3. Pushes and starts the **headset-side relay binary** (``udprelay``) via ``adb push`` + ``adb shell``.
   The headset relay listens on UDP **47998** and tunnels datagrams over TCP to the PC relay.
4. Opens the bookmark with **``serverIP=127.0.0.1``**, **``mediaAddress=127.0.0.1``**,
   **``mediaPort=47998``** — all traffic uses loopback through the ``adb reverse`` + relay tunnel.

The relay binary must be cross-compiled for ``linux/arm64`` (Android). Build it from
``src/core/cloudxr/udprelay/``:

.. code-block:: bash

   cd src/core/cloudxr/udprelay
   GOOS=linux GOARCH=arm64 go build -o udprelay .

Place the binary where the tool can find it (set **``TELEOP_RELAY_BINARY``** or copy to
``cloudxr/native/udprelay`` in the package). Reverse mappings and relay processes are cleaned up on
shutdown.

**``--setup-oob HOST:PORT``** — Wireless. The tool resolves your PC’s LAN address (**``TELEOP_PROXY_HOST``**
or an automatic guess), runs **``adb connect``**, checks for a single device, then listens. After
that, it opens a bookmark using **``https://<LAN>:8080/``** and **``wss://<LAN>:<proxy-port>/…``**. If
the LAN address cannot be determined, set **``TELEOP_PROXY_HOST``** before starting.

**Requirements:** **``adb``** on PATH; exactly one ready device; the pre-built ``udprelay`` binary for
tethered mode (or set **``TELEOP_RELAY_BINARY``**). Failed **``adb reverse``**, relay setup, or
**``am start``** exits the process with code **1**. USB reverse mappings and relay processes are cleaned
up on shutdown.

OOB HTTP and WebSocket share the **same TLS port** as the proxy (**``PROXY_PORT``**, default **48322**).

.. _teleop-stream-defaults:

Stream settings: defaults and how to change them
------------------------------------------------

The hub keeps one merged **``config``** object (often called **``StreamConfig``** in TypeScript). It
includes **streaming target** fields and optional **WebXR client UI** fields. The stock web client
applies only **allowlisted** UI keys so values are validated and mapped to real form controls; the
hub may store other top-level keys from **``setConfig``**, but the browser **ignores** unknown keys.
How to extend that allowlist is covered in :ref:`teleop-oob-integrators`.

**Streaming target fields**

.. list-table::
   :header-rows: 1
   :widths: 22 78

   * - Field
     - Meaning
   * - **``serverIP``**
     - Hostname or IP for CloudXR **signaling** over **TLS** (**``https://``** / **``wss://``** through
       the proxy) the headset uses.
   * - **``port``**
     - TCP port for TLS signaling (normally the proxy port, default **48322**).
   * - **``proxyUrl``**
     - Optional full proxy URL override; empty string clears it.
   * - **``mediaAddress``**
     - Media (UDP) address.
   * - **``mediaPort``**
     - Media (UDP) port (common default **47998** with USB **``adb reverse``**).

**Client UI fields (allowlist)** — same names as Teleop form element **ids** and bookmark query keys:

.. list-table::
   :header-rows: 1
   :widths: 22 78

   * - Field
     - Meaning
   * - **``panelHiddenAtStart``**
     - **``true``** / **``false``** — hide the in-XR control panel when the session starts (query:
       **``true``** / **``false``** or **``1``** / **``0``**).
   * - **``codec``**
     - Preferred video codec: **``h264``**, **``h265``**, or **``av1``** (must match a **``<select>``**
       option on the page).
   * - **``perEyeWidth``**, **``perEyeHeight``**
     - Per-eye resolution in pixels (integers; must satisfy CloudXR validation rules in the UI).

**Order of effect on the headset**

#. **Environment variables** (below) are read when the WSS process starts and seed the hub **initial**
   **``config``** and the **``--setup-oob``** bookmark.
#. On page load, **URL query** parameters seed the form (see :ref:`teleop-headset-control-url`) before
   the OOB socket connects.
#. **``hello``** from the hub sends the merged **``config``** and overrides those seeds.
#. **``GET /api/oob/v1/config``** or WebSocket **``setConfig``** (:ref:`teleop-http-api-oob`) bump
   **``configVersion``** and push **``config``** again.

**Environment variables** — export before **``python -m isaacteleop.cloudxr``** (or restart after change):

.. list-table::
   :header-rows: 1
   :widths: 28 72

   * - Variable
     - Effect
   * - **``PROXY_PORT``**
     - TLS listen port (default **48322**). Initial **``port``** in hub config matches unless
       **``TELEOP_STREAM_PORT``** overrides it.
   * - **``CONTROL_TOKEN``**
     - If set, required on OOB **register**, HTTP **``state``** / **``config``**, and dashboard
       **``setConfig``**. The printed bookmark may include **``controlToken=…``**.
   * - **``TELEOP_STREAM_SERVER_IP``**
     - Initial **``serverIP``** before **``--setup-oob``** adjusts it (USB **``tethered``** forces
       **``127.0.0.1``**).
   * - **``TELEOP_STREAM_PORT``**
     - Initial signaling **``port``**; defaults to proxy port when unset.
   * - **``TELEOP_UDP_RELAY_PORT``**
     - TCP port for the UDP-over-TCP relay tunnel (default **47999**). Used with **``--setup-oob tethered``**.
   * - **``TELEOP_RELAY_BINARY``**
     - Path to the headset-side ``udprelay`` binary. If unset, the tool looks in the package's
       ``native/`` directory.
   * - **``TELEOP_PROXY_HOST``**
     - Wireless: PC address when LAN auto-detect fails.
   * - **``TELEOP_WEB_CLIENT_BASE``**
     - WebXR page base URL only; does not change streaming **``serverIP``** / **``port``**.
   * - **``TELEOP_CLIENT_CODEC``**
     - Initial **``codec``** in hub config and bookmark (e.g. **``h265``**).
   * - **``TELEOP_CLIENT_PANEL_HIDDEN_AT_START``**
     - **``true``** / **``false``** (or **``1``** / **``0``**) → **``panelHiddenAtStart``** in hub + bookmark.
   * - **``TELEOP_CLIENT_PER_EYE_WIDTH``**, **``TELEOP_CLIENT_PER_EYE_HEIGHT``**
     - Integers → **``perEyeWidth``** / **``perEyeHeight``** in hub + bookmark.

**Runtime (no restart):** **``GET …/api/oob/v1/config?…``** with the same flat keys as the HTTP section
below, or WebSocket **``setConfig``** with a JSON **``config``** object (partial merge).

**Manual bookmark:** same query names as :ref:`teleop-headset-control-url`; Python:
**``isaacteleop.cloudxr.wss.build_headset_bookmark_url``** with a **``stream_config``** dict that includes
**``serverIP``**, **``port``**, and any optional fields above.

.. _teleop-simple-chrome-inspect:

Remote inspect and CONNECT (quick reference)
--------------------------------------------

#. **``--setup-oob``** (and **``--wss-only``** if needed) → wait for listen → page opens on headset.
#. PC (Chromium): **``chrome://inspect/#devices``** or **``edge://inspect``** → **inspect** the Teleop tab.
#. In DevTools: click **CONNECT** on the page (required gesture).
#. To disconnect from the PC: in that DevTools window, **reload** the page (e.g. focus the URL bar and
   press **Enter**).

HTTP **state** / **``config``** or WebSocket **``setConfig``** change streaming target and allowlisted
client UI fields; they do **not** start the XR session.

.. _teleop-terminology:

Words that mean more than one thing
------------------------------------

.. list-table::
   :header-rows: 1
   :widths: 28 72

   * - Term
     - In this guide
   * - **Hub**
     - The teleop control service inside the TLS proxy. One shared streaming configuration and
       message routing for all connected clients.
   * - **OOB HTTP**
     - **``GET``** endpoints under **``/api/oob/v1/…``** on the proxy port for scripts and tools.
   * - **WebXR client**
     - Only the **headset browser app** (Isaac Teleop web client).
   * - **WebSocket “client”** in the protocol sections
     - Any program connected to **``/oob/v1/ws``** (headset or operator tool), **not** “CloudXR client”
       by default.
   * - **``dashboard``** role
     - Optional WebSocket client that may send **``setConfig``** only. The name is historical; it is
       **not** the WebXR page.

.. _teleop-http-api-oob:

HTTP API (operator and automation)
-----------------------------------

All of these URLs use **``https://<proxy-host>:<PROXY_PORT>``** and the same TLS certificate as the
proxy. If **``CONTROL_TOKEN``** is set, pass **``?token=…``** or header **``X-Control-Token``**.
Field meanings and environment defaults: :ref:`teleop-stream-defaults`.

.. list-table::
   :header-rows: 1
   :widths: 10 38 22 30

   * - Method
     - Path
     - Auth
     - Response
   * - ``GET``
     - ``/api/oob/v1/state``
     - token if configured
     - **200** JSON snapshot; **401** if token invalid
   * - ``GET``
     - ``/api/oob/v1/config``
     - token if configured
     - **200** with ``changed`` true/false; merges flat query parameters into **``StreamConfig``**
   * - ``OPTIONS``
     - ``*``
     - none
     - CORS preflight

**Config query parameters (flat, URL-encoded):** **``serverIP``**, **``port``**, **``proxyUrl``**,
**``mediaAddress``**, **``mediaPort``**, **``panelHiddenAtStart``** (**``true``** / **``false``**),
**``codec``**, **``perEyeWidth``**, **``perEyeHeight``**, optional **``targetClientId``**,
**``token``**. Example:
``…/config?serverIP=192.168.1.10&port=48322&codec=h265&panelHiddenAtStart=true``. Keys not listed here
can still be merged via WebSocket **``setConfig``**, but the stock WebXR client only applies the
fields documented in :ref:`teleop-stream-defaults`.

Responses include the same CORS headers as the rest of the proxy.

WebSocket endpoint
------------------

.. list-table::
   :widths: 20 80

   * - URL
     - ``wss://<host>:<PROXY_PORT>/oob/v1/ws``
   * - Subprotocol
     - none
   * - Format
     - Text frames: one UTF-8 JSON object per message

Message envelope
~~~~~~~~~~~~~~~~

.. code-block:: json

   { "type": "<string>", "payload": { } }

Unknown **``type``** values produce an **``error``** reply and the payload is ignored.

Messages from clients to the hub
---------------------------------

``register`` (send first)
~~~~~~~~~~~~~~~~~~~~~~~~~~

**Headset:**

.. code-block:: json

   {
     "type": "register",
     "payload": {
       "role": "headset",
       "token": "<optional; required when CONTROL_TOKEN set>",
       "deviceLabel": "<optional human-readable name>"
     }
   }

**Custom operator client** (**``dashboard``** role):

.. code-block:: json

   {
     "type": "register",
     "payload": {
       "role": "dashboard",
       "token": "<optional; required when CONTROL_TOKEN set>"
     }
   }

Reply: **``hello``**. Invalid token → **``error``** (**``UNAUTHORIZED``**) and the connection closes.

``setConfig`` (``dashboard`` only)
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Updates the hub’s **``StreamConfig``**, bumps **``configVersion``**, and pushes **``config``** to
headset(s).

.. code-block:: json

   {
     "type": "setConfig",
     "payload": {
       "token": "<optional>",
       "targetClientId": "<optional uuid; omit to broadcast>",
       "config": {
         "serverIP": "192.168.1.100",
         "port": 48322
       }
     }
   }

**``payload.config``** may be partial; the hub **shallow-merges** at the top level.

``clientMetrics`` (headset only)
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

.. code-block:: json

   {
     "type": "clientMetrics",
     "payload": {
       "t": 1730000000000,
       "cadence": "frame",
       "metrics": {
         "streaming.framerate": 72.0,
         "render.framerate": 90.0,
         "render.pose_to_render_time": 12.5
       }
     }
   }

**``cadence``:** **``frame``** | **``render``**. **``metrics``** keys must use CloudXR **wire**
strings (e.g. **``streaming.framerate``**), not TypeScript enum names.

Messages from the hub to clients
---------------------------------

``hello``
~~~~~~~~~

**To headset:**

.. code-block:: json

   {
     "type": "hello",
     "payload": {
       "clientId": "uuid",
       "configVersion": 1,
       "config": { "<StreamConfig>" }
     }
   }

**To ``dashboard``:**

.. code-block:: json

   {
     "type": "hello",
     "payload": {
       "clientId": "uuid"
     }
   }

``config`` (headset only)
~~~~~~~~~~~~~~~~~~~~~~~~~

Sent when configuration changes (after **``setConfig``** or HTTP config).

.. code-block:: json

   {
     "type": "config",
     "payload": {
       "configVersion": 2,
       "config": { "<StreamConfig — full merged object>" }
     }
   }

.. note::

   If **``config``** arrives while an XR session is already running, apply new settings in memory and
   use them on the **next** connect after a disconnect. Do not tear down the current session
   immediately.

``error``
~~~~~~~~~

.. code-block:: json

   {
     "type": "error",
     "payload": {
       "code": "UNAUTHORIZED | BAD_REQUEST | NOT_FOUND",
       "message": "<human readable>",
       "requestId": "<optional; echo from request>"
     }
   }

``StreamConfig`` (what the hub stores)
--------------------------------------

**Required**

.. list-table::
   :header-rows: 1
   :widths: 20 15 65

   * - Field
     - Type
     - Meaning
   * - ``serverIP``
     - string
     - CloudXR **signaling** host the headset should use
   * - ``port``
     - integer
     - CloudXR signaling port

**Optional**

.. list-table::
   :header-rows: 1
   :widths: 25 20 55

   * - Field
     - Type
     - Meaning
   * - ``proxyUrl``
     - string | null
     - Signaling proxy URL
   * - ``mediaAddress``
     - string
     - Media server address
   * - ``mediaPort``
     - number
     - Media server port

Do **not** rely on toggling “insecure” signaling for this product path: operators should assume
**``https://``** / **``wss://``** only. The hub and bookmark flow do not document or support turning
off TLS for CloudXR signaling here.

The hub keeps one merged config and a monotonic **``configVersion``**. The headset applies this
config before the user starts streaming from the WebXR **CONNECT** control.

``GET /api/oob/v1/state`` response shape
-----------------------------------------

.. code-block:: json

   {
     "updatedAt": 1730000000000,
     "configVersion": 2,
     "config": { "<StreamConfig>" },
     "headsets": [
       {
         "clientId": "uuid",
         "connected": true,
         "deviceLabel": "string or null",
         "registeredAt": 1730000000000,
         "metricsByCadence": {
           "frame": { "at": 1730000000000, "metrics": { "streaming.framerate": 72.0 } },
           "render": { "at": 1730000000000, "metrics": { "render.framerate": 90.0 } }
         }
       }
     ],
     "dashboards": [
       {
         "clientId": "uuid",
         "connected": true,
         "registeredAt": 1730000000000
       }
     ]
   }

**Metrics:** the hub stores the latest **``clientMetrics``** per cadence per headset and does **not**
push them to **``dashboard``** clients—poll this endpoint. **``updatedAt``** is when the snapshot was
built; use **``metricsByCadence`` … ``at``** for sample time.

There is **no** **``logs``** field in v1. **``dashboards``** lists WebSocket clients that registered
with **``role: "dashboard"``**.

.. _teleop-headset-control-url:

WebXR page URL query parameters
--------------------------------

The web client reads these from the **page URL** when it loads (build one long URL; users open it on
the headset). Defaults, env vars, and hub precedence: :ref:`teleop-stream-defaults`.

.. list-table::
   :header-rows: 1
   :widths: 25 75

   * - Parameter
     - Purpose
   * - ``oobEnable``
     - If **``1``** or **``true``**, open the OOB WebSocket at
       **``wss://{serverIP}:{port}/oob/v1/ws``** using the **``serverIP``** and **``port``** query
       parameters (same as streaming). **``--setup-oob``** bookmarks set this automatically. If
       **``oobEnable``** is off, or **``serverIP``** / **``port``** are missing or invalid, the client
       does **not** connect to OOB.
   * - ``controlToken``
     - Sent in **``register``**; must match **``CONTROL_TOKEN``** on the server when set.
   * - ``serverIP``, ``port``, ``proxyUrl``, ``mediaAddress``, ``mediaPort``
     - Seed streaming target fields at load. Hub **``hello``** / **``config``** still **override** when
       **``configVersion``** increases.
   * - ``panelHiddenAtStart``, ``codec``, ``perEyeWidth``, ``perEyeHeight``
     - Optional allowlisted **client UI** seeds (same semantics as :ref:`teleop-stream-defaults`).
       **``panelHiddenAtStart``**: **``true``** / **``false``** or **``1``** / **``0``**.

Getting the link onto the headset without typing
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

* Copy the **bookmark line** from the terminal or build the same string with
  **``isaacteleop.cloudxr.wss.build_headset_bookmark_url``** in Python if you script adb yourself.
* **``--setup-oob``** runs **``adb shell am start -a android.intent.action.VIEW -d '<url>'``** for you;
  quote the whole URL because **``&``** appears in query strings.
* Or email/chat the link to yourself and open it in the headset browser.

.. _teleop-user-activation:

WebXR user activation (why CONNECT matters)
--------------------------------------------

**``navigator.xr.requestSession()``** usually needs a **user gesture**. The practical approach: use
Chromium **remote inspect** and click **CONNECT** on the Teleop UI (same as tapping CONNECT on the
device).

**Disconnect from the PC:** With the Teleop tab still open in DevTools, **reload** the page—click the
**URL** in the inspector address bar and press **Enter** (or use refresh). That ends the session
without using the headset.

After the first successful gesture, later **connect** / **disconnect** cycles often work with less
interaction.

Security
--------

The hub decides **which streaming endpoint** the headset uses. Treat the proxy port and token like
admin access: use **``CONTROL_TOKEN``** in real deployments, keep traffic on trusted networks or VPNs,
and remember TLS uses the same certificates as the CloudXR proxy.

.. _teleop-wss-only-testing:

Local testing without the CloudXR runtime
------------------------------------------

**Unit tests** (hub logic only)::

   cd src/core/cloudxr_tests/python
   pip install -e ".[test]"
   pytest -q

**Proxy + hub + adb** (no CloudXR process)::

   python -m isaacteleop.cloudxr --wss-only --setup-oob tethered --accept-eula

Install **``isaacteleop``** from your wheel, editable install, or point **``PYTHONPATH``** at your CMake
**``build/python_package/<Config>``** output. Logs go to stderr. Other WebSocket paths still expect a
runtime on localhost—stick to teleop URLs in this mode, or drop **``--wss-only``**.

Check the hub:

.. code-block:: bash

   curl -k https://127.0.0.1:48322/api/oob/v1/state

If **``curl``** works but a browser shows strange **RPC** or **“stateful work request”** messages, try a
normal browser window, **Incognito** (extensions off), or another profile—corporate extensions and
local security tools sometimes intercept **``https://127.0.0.1``**. The proxy does not speak gRPC to
the runtime in **``--wss-only``** mode; odd messages usually come from the browser environment.

.. _teleop-oob-integrators:

For integrators (architecture, metrics, code)
----------------------------------------------

This section is for **automation**, **internal tools**, and **engineers** changing the web client or hub.
Operators can skip it.

**Architecture (control plane)**

* The **TLS proxy** on the streaming host listens on **``PROXY_PORT``** (default **48322**). It terminates
  **HTTPS** and **WSS** for CloudXR signaling and, when **``--setup-oob``** is used, hosts the **hub** on
  **``/oob/v1/ws``** and OOB **HTTPS** under **``/api/oob/v1/…``**.
* The **headset** loads the WebXR page, opens **``wss://…/oob/v1/ws``** when **``oobEnable``** is set, and
  receives **``hello``** / **``config``** with the merged **``StreamConfig``**. Media and poses still use
  the normal streaming path—not OOB.
* **Operator / dashboard** clients may **GET** **``/api/oob/v1/state``** and **``/api/oob/v1/config``**
  or connect as WebSocket **``dashboard``** and send **``setConfig``**. Protocol details:
  :ref:`teleop-http-api-oob` and the **WebSocket** message sections earlier in this page.

**Metrics**

* Headsets may send **``clientMetrics``** over the OOB WebSocket (see the **``clientMetrics``** message
  shape above). The hub keeps the latest sample per **cadence** per headset.
* Integrators read metrics from **``GET /api/oob/v1/state``**: each headset entry includes
  **``metricsByCadence``** with timestamps—there is **no** push to **``dashboard``** clients; **poll**
  **``/api/oob/v1/state``** on an interval that fits your tooling.

**Extending hub-driven UI fields**

A free-form “set any form field by id” API is brittle (typos, internal ids changing, **``<select>``**
option sets, security if the page ever mixed admin and user content). The supported pattern is: add the
**HTML id** and hub key name (usually the same string), extend **``_stream_config_from_query``** /
bookmark encoding in **``wss.py``**, extend **``streamConfigFromUrlSearchParams``** in **``App.tsx``**,
and add coercion in **``CloudXR2DUI``** (see **``HUB_CLIENT_UI_FIELDS``** in **``CloudXR2DUI.tsx``**).

**Source files**

.. list-table::
   :header-rows: 1
   :widths: 30 70

   * - Area
     - Location
   * - Hub logic
     - :code-file:`oob_teleop_hub.py <src/core/cloudxr/python/oob_teleop_hub.py>`
   * - TLS proxy, HTTP, adb, bookmark URL
     - :code-file:`wss.py <src/core/cloudxr/python/wss.py>`
   * - PC-side UDP-over-TCP relay
     - :code-file:`udp_tcp_relay.py <src/core/cloudxr/python/udp_tcp_relay.py>`
   * - Headset-side UDP relay (Go)
     - ``src/core/cloudxr/udprelay/main.go``
   * - CLI (**``--wss-only``**, **``--setup-oob``**, **``OobAdbError``** → exit 1)
     - :code-file:`__main__.py <src/core/cloudxr/python/__main__.py>`
   * - Headset control channel (TypeScript)
     - ``deps/cloudxr/webxr_client/helpers/controlChannel.ts``
   * - Headset UI wiring (React)
     - ``deps/cloudxr/webxr_client/src/App.tsx``
