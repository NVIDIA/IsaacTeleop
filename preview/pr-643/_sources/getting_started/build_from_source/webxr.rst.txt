.. SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
.. SPDX-License-Identifier: Apache-2.0

Build WebXR Client
==================

.. tip::

   A prebuilt CloudXR web client is available at https://nvidia.github.io/IsaacTeleop/client/main/.
   You only need to build from source if you want to customize the client.

The Isaac Teleop WebXR client is built with React, Three.js, and WebXR. It streams VR/AR content
from a CloudXR Runtime server to the browser.  For more details about CloudXR.js SDK and its advanced features, see the
`CloudXR.js documentation`_.

The source is located at :code-file:`deps/cloudxr/webxr_client/ <deps/cloudxr/webxr_client/>`.

.. contents:: Steps
   :local:
   :depth: 1

Prerequisites
-------------

- Node.js (v20 or higher)

1. Download CloudXR.js SDK
--------------------------

From the project root:

.. code-block:: bash

   source deps/cloudxr/webxr_client/scripts/setup_cloudxr_env.sh
   deps/cloudxr/webxr_client/scripts/download_cloudxr_sdk.sh

This will automatically download the CloudXR.js SDK and place it in ``deps/cloudxr/nvidia-cloudxr-6.1.0.tgz``.  The
`package.json` is configured to install the SDK from this local file.

2. Install dependencies
-----------------------

From the ``deps/cloudxr/webxr_client/`` directory:

.. code-block:: bash

   npm install ../nvidia-cloudxr-6.1.0.tgz

3. Build & Run
--------------

Development build (one-shot)
~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Outputs to ``./build/`` with source maps for debugging:

.. code-block:: bash

   npm run dev

Development server (with hot reload)
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Starts a webpack dev server on ``http://localhost:8080`` with hot module replacement:

.. code-block:: bash

   npm run dev-server

For **HTTPS** (required by WebXR on most browsers):

.. code-block:: bash

   npm run dev-server:https

This starts the dev server with a self-signed certificate on ``https://localhost:8080``.  You can follow the same
instructions to use the WebXR client as documented in the :ref:`Quick Start Guide <connect-quest-pico>`.


..
   References
.. _`CloudXR.js documentation`: https://docs.nvidia.com/cloudxr-sdk/latest/usr_guide/cloudxr_js/index.html
