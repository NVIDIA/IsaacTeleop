.. SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
.. SPDX-License-Identifier: Apache-2.0

Quick Start
===========

This guide walks through running a teleoperation session with an XR headset using CloudXR. By the
end you will have the retargeting pipeline processing live hand/controller data and printing gripper
commands to the terminal.

.. contents:: Steps
   :local:
   :depth: 1

1. Check out code base (Optional)
---------------------------------

Clone the repository and enter the project directory:

.. code-block:: bash

   git clone https://github.com/NVIDIA/IsaacTeleop.git
   cd IsaacTeleop

As a quick start guide, we don't need to build the code base from source. However, we still need
to clone the repository for a couple quick samples to run.

2. Install the ``isaacteleop`` pip package
------------------------------------------

In a new terminal, install the package from PyPI (or from a local wheel if you built from source):

.. code-block:: bash

   # From PyPI
   pip install isaacteleop[cloudxr,retargeters]~=1.0.0 --extra-index-url https://pypi.nvidia.com

Instead of installing the package from PyPI, you can build from source and install the local wheel.
See :doc:`build_from_source` for more details.

.. _run-cloudxr-server:

3. Run CloudXR Server
---------------------

Start the CloudXR runtime. The first run downloads the CloudXR Web Client SDK
and asks you to review and accept the EULA:

.. code-block:: bash

   python -m isaacteleop.cloudxr

To bypass the interactive EULA prompt (e.g. for CI or headless runs), pass the flag:

.. code-block:: bash

   python -m isaacteleop.cloudxr --accept-eula

You should see output similar to:

.. figure:: ../_static/cloudxr-run-output.png
   :alt: CloudXR run output
   :align: center

   **Figure:** CloudXR run output

.. important::

   Keep this terminal open — CloudXR must stay running for the duration of the session. Open a
   **new terminal** for the remaining steps.

   Also take note of the ``source /home/dev/.cloudxr/run/cloudxr.env`` path it mentioned in the
   output. You will need to source it in step :ref:`load-cloudxr-environment-variables`.

CloudXR Configurations (Optional)
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

You can also inspect the CloudXR environment variables by running:

.. code-block:: bash

   cat ~/.cloudxr/run/cloudxr.env

You should see:

.. code-block:: text

   export NV_DEVICE_PROFILE=auto-webrtc
   ...

By default, the CloudXR runtime is configured to use the ``auto-webrtc`` device profile for Pico &
Quest headsets. For Apple Vision Pro, the runtime is configured to use the ``auto-native`` device
profile.

To do that, you can override CloudXR configurations by creating an ``env`` file and pass it to the
CloudXR runtime via the ``--cloudxr-env-config`` argument.

.. code-block:: bash

   echo 'NV_DEVICE_PROFILE=auto-native' > custom.env
   python -m isaacteleop.cloudxr --cloudxr-env-config=./custom.env

Again, you can also inspect the CloudXR environment variables by looking at the
``~/.cloudxr/run/cloudxr.env`` file:

.. dropdown:: Custom CloudXR configurations

   .. list-table:: Custom CloudXR configurations
      :header-rows: 1
      :widths: 20 15 30 20
      :width: 100%

      * - Variable
        - Default
        - Description
        - Possible Values
      * - NV_DEVICE_PROFILE
        - ``auto-webrtc``
        - Custom device profile to use
        - | ``auto-webrtc``
          | ``auto-native``
          | ``Quest3``
          | ``AppleVisionPro``
      * - NV_CXR_ENABLE_PUSH_DEVICES
        - ``true``
        - Enable or disable push device overseer for hand tracking
        - | ``true``
          | ``false``
      * - NV_CXR_FILE_LOGGING
        - ``true``
        - Enable or disable file-based logging, when disabled logs are printed to the console
        - | ``true``
          | ``false``

.. code-block:: bash

   export NV_DEVICE_PROFILE=auto-native
   ...

4. Whitelist ports for Firewall
-------------------------------

CloudXR requires certain network ports to be open. Depending on your firewall configuration, you
might need to whitelist them manually.

.. dropdown:: Meta Quest and Pico headsets
   :open:

   For **Quest and Pico headsets** (WebXR Client), at the minimum, you need to whitelist the ports
   for the CloudXR runtime and wss proxy:

   .. code-block:: bash

      sudo ufw allow 47998/udp
      sudo ufw allow 49100,48322/tcp

   If you are running the WebXR client from source, you need to whitelist the additional ports for
   the web server:

   .. code-block:: bash

      sudo ufw allow 8080,8443/tcp

.. dropdown:: Vision Pro client

   For **Vision Pro client**, you need to whitelist the ports for the CloudXR runtime and wss proxy:

   .. code-block:: bash

      sudo ufw allow 48010,48322/tcp
      sudo ufw allow 47998:48000,48005,48008,48012/udp

Please see the `CloudXR network setup`_ for more details for other network configurations (such as
running the CloudXR runtime and wss proxy in containerized environment; or using Vision Pro client).

5. Connect an XR headset
------------------------

.. _connect-quest-pico:

.. dropdown:: Meta Quest and Pico headsets
   :open:

   To stream from a Meta Quest or PICO headset, you will need a CloudXR web client. For your
   convenience, we host a prebuilt CloudXR web client at `nvidia.github.io/IsaacTeleop/client`_.
   You can just open this URL in your headset's browser. No need to build or install a separate client.

   .. tip::

      For quick validation, you can also open the `nvidia.github.io/IsaacTeleop/client`_ URL in a
      desktop browser. IWER (Immersive Web Emulator Runtime) will automatically load to emulate a Meta
      Quest 3 headset.

   .. tab-set::
      .. tab-item:: CloudXR web client

         .. figure:: ../_static/cloudxr-web-client-howto.png
            :alt: CloudXR web client usage instruction
            :align: center

            **Figure:** CloudXR web client usage instruction

      .. tab-item:: Privacy warning

         .. figure:: ../_static/cloudxr_accept_cert_not_private.png
            :alt: Browser privacy warning for self-signed certificate

            **Figure:** Browser privacy warning for self-signed certificate

      .. tab-item:: Certificate accepted

         .. figure:: ../_static/cloudxr_accept_cert_accepted.png
            :alt: Certificate accepted page

            **Figure:** Certificate accepted page

   As illustrated in the figure above, there are 3 steps to connect to your headset:

   1. Enter the IP address of the workstation running CloudXR
   2. Accept the self-signed SSL certificate, which was created automatically during :ref:`run-cloudxr-server`:

      - Click the **Click https://<ip>:48322/ to accept cert** link that appears on the page.
      - In the new tab, you will see a **"Your connection is not private"** warning. Click **Advanced**, then **Proceed to <ip> (unsafe)**.
      - Once accepted, the page will show **Certificate Accepted**. Navigate back to the CloudXR.js client page.
   3. Click **Connect** to begin teleoperation.

   .. note::
      For advanced usage and troubleshooting of CloudXR, see the `CloudXR documentation`_ for more
      details.

   The source code for the web client is in the :code-dir:`deps/cloudxr/webxr_client/` directory.
   Follow the instructions in the official `CloudXR.js documentation`_ for more details if you want to
   run the web client from source.

.. _connect-apple-vision-pro:

.. dropdown:: Apple Vision Pro

   For Apple Vision Pro, you will need to build and install the Isaac XR Teleop Sample Client. Follow
   the instructions in the `Isaac XR Teleop Sample Client for Apple Vision Pro`_ repository to build
   and install the sample client on your Apple Vision Pro.

   .. note::

      You will need v3.0.0 or newer of the `Isaac XR Teleop Sample Client for Apple Vision Pro`_
      to connect to Isaac Teleop.


.. _load-cloudxr-environment-variables:

6. Load CloudXR environment variables
--------------------------------------

Open a new terminal and source the CloudXR environment variables posted from the CloudXR runtime in
:ref:`run-cloudxr-server`:

Source the setup script so that the OpenXR runtime points to CloudXR:

.. code-block:: bash

   source ~/.cloudxr/run/cloudxr.env

.. important::

   Make sure to run the rest of the commands in the same terminal. Or if have to open a new
   terminal, source the CloudXR environment variables again.

7. Run a teleop example
-----------------------

Run the simplified gripper retargeting example. This demonstrates the full
pipeline: reading XR controller input via CloudXR, retargeting it through the
``GripperRetargeter``, and printing the resulting gripper command values:

.. code-block:: bash

   python examples/teleop/python/gripper_retargeting_example_simple.py

Once running, squeeze the controller triggers on your XR headset to control
the gripper. You should see periodic status output:

.. code-block:: text

   ============================================================
   Gripper Retargeting - Squeeze triggers to control grippers
   ============================================================

   [  0.5s] Right: 0.00
   [  1.0s] Right: 0.73
   [  1.5s] Right: 1.00
   ...

The example runs for 20 seconds and then exits. To try other examples, see
``examples/teleop/python/`` — for instance:

- ``se3_retargeting_example.py`` — maps hand or controller poses to
  end-effector poses (absolute or relative)
- ``dex_bimanual_example.py`` — bimanual dexterous hand retargeting
- ``gripper_retargeting_example.py`` — full gripper example with more
  configuration options

Next steps
----------

.. grid:: 2
   :gutter: 3

   .. grid-item-card::

      .. image:: ../_static/isaaclab.jpg
         :alt: Isaac Lab

      ^^^^^^^^^^^^^

      **Teleoperation in Isaac Lab**

      Follow instructions in `Teleoperation and Imitation Learning with Isaac Lab Mimic`_ to know
      more about how to collect demonstrations with Isaac Lab and how to augment them with Isaac
      Lab Mimic and train imitation learning policies.

      If you are new to Isaac Lab, follow instructions in `Isaac Lab Quick Start`_ to get started.

   .. grid-item-card::

      .. image:: ../_static/isaacros.png
         :alt: Isaac ROS

      ^^^^^^^^^^^^^

      **Teleoperation with Isaac ROS**

      Check out the :code-dir:`examples/teleop_ros2/` directory for an example on how to make a
      ROS 2 message publisher using Isaac Teleop.

      We are also working on a Unitree G1-based end-to-end teleoperation, data collection, and
      imitation learning solution for ROS2 in an upcoming `Isaac ROS`_ release. Stay tuned!

      .. rst-class:: trademark-notice

      *ROS is a trademark of Open Robotics.*

More Information
----------------

- :doc:`teleop_session` — learn how ``TeleopSession`` works and how to build
  custom retargeting pipelines
- :doc:`build_from_source` — build the C++ core, Python bindings, and plugins
  from source

..
   References
.. _`nvidia.github.io/IsaacTeleop/client`: https://nvidia.github.io/IsaacTeleop/client
.. _`CloudXR documentation`: https://docs.nvidia.com/cloudxr-sdk/latest/index.html
.. _`CloudXR.js documentation`: https://docs.nvidia.com/cloudxr-sdk/latest/usr_guide/cloudxr_js/index.html
.. _`Isaac XR Teleop Sample Client for Apple Vision Pro`: https://github.com/isaac-sim/isaac-xr-teleop-sample-client-apple
.. _`Isaac Lab Quick Start`: https://isaac-sim.github.io/IsaacLab/main/source/setup/quickstart.html
.. _`Teleoperation and Imitation Learning with Isaac Lab Mimic`: https://isaac-sim.github.io/IsaacLab/main/source/overview/imitation-learning/teleop_imitation.html#teleoperation-imitation-learning
.. _`CloudXR network setup`: https://docs.nvidia.com/cloudxr-sdk/latest/requirement/network_setup.html#ports-and-firewalls
.. _`Isaac ROS`: https://nvidia-isaac-ros.github.io
