.. SPDX-FileCopyrightText: Copyright (c) 2026 j-mex. All rights reserved.
.. SPDX-License-Identifier: Apache-2.0

.. _jmex-moxi-plugin:

j-mex AgileMaster
=================

Use the `j-mex AgileMaster <https://jmex.com.tw/agilemaster/>`_ inertial motion capture system with
the Isaac Teleop framework. The operator wears the suit and the joint angles arrive over the network,
so unlike the leader arms on the :doc:`generic joint-space path <joint_space>` there is no mechanism
on the desk. Linux x86_64.

AgileMaster has three parts: the **j-mex Mocap Suit** the operator wears, **MOXI Player** — the
vendor application that reads the suit, retargets the motion onto a robot URDF and streams the result
on a numbered channel — and the **MOXI Receiver SDK** this plugin links against. Because Player has
already solved the retargeting, the channel carries the target robot's own named joint angles, ready
for the joint-space path.

.. contents:: On this page
   :local:
   :depth: 2

Components
----------

- **Core library** (``jmex_plugin_core``) — owns the MOXI receiver session and turns one channel's
  frames into the published payload.
- **Plugin executable** (``jmex_plugin``) — the plugin binary; one OpenXR session, one publisher.
- **CLI tool** (``jmex_joint_state_printer``) — reads back what the plugin publishes with no Python
  and no retargeting graph in the way.

Prerequisites
-------------

- **Linux** — x86_64.
- **MOXI Receiver SDK**, 1.1 or newer — see :ref:`jmex-getting-the-software`.
- **MOXI Player for Robot** — the vendor application, on this machine or another on the same subnet.
- **CloudXR runtime** — the tensor transport is an OpenXR runtime feature, so the runtime is a hard
  requirement even though nothing here is a headset.

Quick Start
-----------

.. _jmex-getting-the-software:

Step 1: Get the SDK and MOXI Player
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Neither the MOXI Receiver SDK nor MOXI Player is a public download, and Player additionally needs a
licence key to run. Contact us through the `AgileMaster product page
<https://jmex.com.tw/agilemaster/>`_ to request access; we will supply the SDK, the Player build for
your platform, and a key. The SDK itself is Apache-2.0.

Ask for **Receiver SDK 1.1 or newer** — this plugin does not build against earlier releases.

Step 2: Build the plugin
~~~~~~~~~~~~~~~~~~~~~~~~

Unpack the SDK into the plugin's own directory as ``src/plugins/jmex/MOXIReceiverSDK/``, so that
``src/plugins/jmex/MOXIReceiverSDK/sdk/linux-x64/lib/cmake/MOXIReceiverSDK/`` exists. No build flags
are then needed:

.. code-block:: bash

   cmake -B build
   cmake --build build --parallel
   cmake --install build

That directory is covered by the plugin's ``.gitignore``: the SDK is obtained from j-mex rather than
fetched by the build, so it is yours to place and not repository content — the same arrangement the
manus and wuji_glove plugins use for theirs.

To keep the SDK elsewhere, point ``CMAKE_PREFIX_PATH`` or ``JMEX_SDK_ROOT`` (a CMake or environment
variable) at the SDK's platform directory — the one containing ``lib/cmake/MOXIReceiverSDK``. Both
take precedence over a copy unpacked in the plugin directory; ``JMEX_SDK_ROOT`` is searched first and
warns rather than falling back silently when it holds no SDK the plugin can use. Either way, the
configure output names the SDK that answered:

.. code-block:: bash

   cmake -B build -DJMEX_SDK_ROOT=/path/to/MOXIReceiverSDK-1.1.0/sdk/linux-x64
   # -- jmex plugin: MOXIReceiverSDK 1.1.0 from .../sdk/linux-x64/lib/cmake/MOXIReceiverSDK

CMake skips the whole plugin when no SDK is found, so a tree without it still builds. If the plugin
is missing from your build, look for ``Skipping jmex plugin build:`` in the configure output.

Step 3: Start the CloudXR runtime
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

The tensor transport is an OpenXR runtime feature, so the runtime is a hard requirement even though
nothing here is a headset. In one terminal, and keep it running for the session:

.. code-block:: bash

   python -m isaacteleop.cloudxr.service run

The runtime needs a **concrete device profile**, and the default — ``Quest3`` — already is one. An
``auto-*`` profile resolves the device from whichever client connects, so with no client there is no
system and the plugin dies at startup with ``Failed to get OpenXR system: -35``
(``XR_ERROR_FORM_FACTOR_UNAVAILABLE``). To choose a different one, hand the service an env file,
which takes precedence over the process environment:

.. code-block:: bash

   echo NV_DEVICE_PROFILE=AppleVisionPro > cloudxr.env
   python -m isaacteleop.cloudxr.service run --cloudxr-env-config cloudxr.env

Then, **in every terminal you start the plugin or the printer from**, load the environment the
service wrote. Both are native OpenXR applications that do not embed ``CloudXRLauncher``, so nothing
points their loader at CloudXR until this is sourced:

.. code-block:: bash

   source ~/.cloudxr/run/cloudxr.env

See :ref:`load-cloudxr-environment-variables` for the full explanation.

Step 4: Run the plugin
~~~~~~~~~~~~~~~~~~~~~~

In a terminal with ``cloudxr.env`` sourced:

.. code-block:: bash

   # Defaults: channel 1, collection "jmex"
   ./install/plugins/jmex/jmex_plugin

   # Player's file replay is fixed on channel 255
   ./install/plugins/jmex/jmex_plugin --channel=255

Isaac Teleop can start it for you instead — see `Letting Isaac Teleop launch the plugin`_.

The receiver is the TCP server and Player is the client — the direction is the opposite of what the
data flow suggests — so the plugin waits to be paired, and keeps waiting if Player disconnects and
comes back.

Only **one instance per machine**: the receiver is process-global, and the plugin holds the SDK's TCP
server port at its default rather than taking it from the command line, so a second instance finds
that port taken.

Step 5: Stream from MOXI Player
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Start Player and stream, following its own README and glove guide — setup, calibration and operation
are documented with the application. Two things have to line up with this plugin:

- **The channel.** Both ends must open the same number. The plugin defaults to ``1``, the live
  default. **Player's file replay is fixed on 255**, so verifying from a recorded capture means
  passing ``--channel=255``.
- **The robot.** Load the same robot in Player as in your Isaac Teleop scene. The joint angles
  describe the robot Player loaded, not the operator.

Replaying a recorded motion file works the same way — it streams real data down the real wire
protocol, so everything from this plugin onwards behaves as it does with someone wearing the suit.

Step 6: Verify the transport
~~~~~~~~~~~~~~~~~~~~~~~~~~~~

``jmex_joint_state_printer`` reads the collection the plugin publishes on, so it separates "the
device path works" from "my pipeline is misconfigured". It is a downstream consumer, not a second
receiver: **leave the plugin running** and start the printer in another terminal — sourcing
``cloudxr.env`` there too, since it is a native OpenXR application of its own.

.. code-block:: bash

   source ~/.cloudxr/run/cloudxr.env
   ./install/plugins/jmex/jmex_joint_state_printer jmex

Printing nothing means no sample has arrived yet — the plugin is not running, or Player has not
paired.

Consuming the data
------------------

Wire a ``JointStateSource`` into your retargeting graph on the collection the plugin publishes on:

.. code-block:: python

   from isaacteleop.retargeting_engine.deviceio_source_nodes import JointStateSource

   source = JointStateSource(
       name="agilemaster",    # this node's name in your graph; yours to choose
       collection_id="jmex",  # must match the plugin's collection
       joint_names=[...],     # the robot's DOF names, as Player reports them
   )

``collection_id`` is the only one of the three that has to agree with the plugin; ``name`` only has
to be unique among your graph's nodes.

Each frame's joints are looked up against ``joint_names`` by name, so the wire order does not matter
and a subset is fine — list the DOFs your retargeting graph drives. The order you give here is the
order the downstream consumer sees, though, so it has to match what that consumer expects (for
example :code-file:`JointStateRetargeterConfig.device_joints
<src/python/isaacteleop/retargeters/joint_space/joint_state_retargeter.py>`). Run
``jmex_joint_state_printer`` to see the exact names your Player is sending.

Letting Isaac Teleop launch the plugin
--------------------------------------

``TeleopSession`` can own the plugin process for you, starting it on entry and stopping it on exit.
Add a ``PluginConfig`` naming this plugin and pointing at an **installed** tree:

.. code-block:: python

   from pathlib import Path
   from isaacteleop.teleop_session_manager import PluginConfig, TeleopSessionConfig

   session_config = TeleopSessionConfig(
       app_name="AgileMasterTeleop",
       pipeline=pipeline,
       plugins=[
           PluginConfig(
               plugin_name="jmex",     # plugin.yaml's name
               plugin_root_id="jmex",
               search_paths=[Path("install/plugins")],
           )
       ],
   )

The search path holds the ``plugins/`` directory ``cmake --install`` writes, not the build tree — a
plugin that has only been built is not discoverable. To pass a different channel, append
``plugin_args=["--channel=255"]`` — replaying a recorded capture is the usual reason to; it lands
after ``plugin.yaml``'s ``args`` and the last value of a flag wins.

Two things are worth knowing before this is your setup:

- **A search path that does not exist, or a name no ``plugin.yaml`` declares, is skipped in silence.**
  Nothing is raised, so the symptom is not an error but a first sample that never arrives. Check the
  path yourself before handing it over if you want a clear failure.
- **``--plugin-root-id=<id>`` is injected ahead of everything you supply.** This plugin ignores it,
  but a plugin of your own that reads positional arguments would misread that one as the first.

Starting the plugin yourself stays supported and is the better shape while bringing a device up: the
plugin can be restarted without restarting the simulator, Player re-pairs on its own, and the two
processes' logs stay apart.

What the plugin publishes
-------------------------

.. list-table::
   :header-rows: 1
   :widths: 25 75

   * - Collection
     - ``jmex`` by default; the plugin's ``--collection-id``
   * - Schema
     - ``JointStateOutput``
   * - Consumer
     - ``JointStateSource``
   * - Contents
     - Every **revolute** joint of the loaded robot: name, angle [rad], angular velocity [rad/s]

This is a **mapping, not a conversion**: Player's joint name becomes ``JointState.name`` verbatim,
its rotation angle becomes ``position``, its angular velocity becomes ``velocity``. The consumer's
``joint_names`` are therefore matched by name and wire order does not matter. Root and fixed joints
carry no angle and are not actuated degrees of freedom, so they are not published.

Important information
---------------------

**Where Player runs.** One machine or two, started in either order. The receiver's advertisements are
sent from an ephemeral source port, leaving UDP ``10100`` — the port Player listens on — free for a
Player on the same host. Two hosts remain the right layout when the operator is not sitting at the
simulation machine; they must then be on the same subnet, because the advertisement is a
``255.255.255.255`` limited broadcast that routers do not forward. On wireless networks, access-point
client isolation blocks it too — suspect that before suspecting the plugin.

This plugin requires Receiver SDK 1.1 or newer, and 1.1.0 is the first release j-mex has shipped to
anyone, so the one-or-two-hosts choice above is the only arrangement it has ever had.

**The product line must match.** This plugin opens the robot dialect, and a robot-line Player does
not downgrade. Pointing it at a general-line Player desynchronizes the parse rather than failing
cleanly.

**There is no synthetic backend**, unlike the leader arms. The SDK is required to build the plugin
and Player is required to feed it, so without the vendor stack it cannot be exercised at all.
Replaying a recorded file removes the Mocap Suit and the operator, but not the vendor software.

Troubleshooting
---------------

.. list-table::
   :header-rows: 1
   :widths: 40 60

   * - Symptom
     - What to check
   * - Plugin waits at ``Waiting for MOXI Player to pair`` forever
     - Player is streaming, and **on the same channel number** — a mismatch is indistinguishable
       from Player not running at all; on a two-host setup, both hosts on the same subnet and
       access-point client isolation on wireless
   * - ``Failed to get OpenXR system: -35``
     - ``~/.cloudxr/run/cloudxr.env`` has not been sourced in this terminal; or the runtime is not
       running; or it is running with an ``auto-*`` device profile
   * - ``Skipping jmex plugin build:`` at configure time
     - No SDK in ``src/plugins/jmex/MOXIReceiverSDK/``, and ``CMAKE_PREFIX_PATH`` /
       ``JMEX_SDK_ROOT`` does not point at an SDK platform directory either
   * - Joint names do not match the robot asset
     - Player is loaded with a different robot; run ``jmex_joint_state_printer`` to see what is
       actually being sent
   * - ``no revolute joints on channel`` warning
     - Player is on the general product line; this plugin opens the robot dialect

Everything upstream of the channel — the suit, the gloves, the dongle, Player's own setup and
calibration — is covered by Player's README and glove guide, not here.

License
-------

Source files here are Apache-2.0, as is the MOXI Receiver SDK they link against. The SDK is still
not redistributed by this project — it is obtained from j-mex, not fetched by the build. MOXI Player
is a separate proprietary application under its own terms.

See the :code-file:`plugin README <src/plugins/jmex/README.md>` for the build and run steps beside
the installed binary.
