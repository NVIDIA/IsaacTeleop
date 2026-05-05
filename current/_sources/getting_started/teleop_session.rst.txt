.. SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
.. SPDX-License-Identifier: Apache-2.0

Teleop Session
==============

TeleopSessionManager provides a declarative, configuration-based API for
setting up complete teleop pipelines. It eliminates boilerplate code and makes
examples more readable by focusing on **what** you want to do rather than
**how** to set it up.

Overview
--------

The main component is :code-file:`TeleopSession <src/core/teleop_session_manager/python/teleop_session.py>`, which manages the complete lifecycle
of a teleop session. It wraps the lower-level
:code-file:`DeviceIOSession <src/core/deviceio/cpp/inc/deviceio/deviceio_session.hpp>`
and :doc:`device trackers <../device/trackers>` so that callers don't need to
manage them directly:

#. Creates and configures trackers (head, hands, controllers)
#. Sets up OpenXR session with required extensions
#. Initializes and manages plugins
#. Runs retargeting pipeline with automatic updates
#. Handles cleanup via RAII

Quick Start
-----------

Here's a minimal example:

.. code-block:: python

   from isaacteleop.teleop_session_manager import (
       TeleopSession,
       TeleopSessionConfig,
   )
   from isaacteleop.retargeting_engine.deviceio_source_nodes import ControllersSource
   from isaacteleop.retargeting_engine.examples import GripperRetargeter

   # Create source and build pipeline
   controllers = ControllersSource(name="controllers")
   gripper = GripperRetargeter(name="gripper")
   pipeline = gripper.connect({
       "controller_left": controllers.output("controller_left"),
       "controller_right": controllers.output("controller_right")
   })

   # Configure session
   config = TeleopSessionConfig(
       app_name="MyTeleopApp",
       pipeline=pipeline,
       trackers=[],  # Auto-discovered
   )

   # Run!
   with TeleopSession(config) as session:
       while True:
           result = session.step()
           # Access outputs
           left = result["gripper_left"][0]
           right = result["gripper_right"][0]

Configuration Classes
---------------------

.. note::
    Currently, to customize the teleop session, you need to configure it via Python code. We are
    working on a more declarative configuration API that takes a YAML file as input. Follow the
    following issue for progress: https://github.com/NVIDIA/IsaacTeleop/issues/229

TeleopSessionConfig
^^^^^^^^^^^^^^^^^^^

The main configuration object:

.. code-block:: python

   @dataclass
   class TeleopSessionConfig:
       app_name: str                            # OpenXR application name
       pipeline: Any                            # Connected retargeting pipeline
       mode: SessionMode = SessionMode.LIVE     # LIVE or REPLAY
       trackers: List[Any] = []                 # Tracker instances (optional)
       plugins: List[PluginConfig] = []         # Plugin configurations (optional)
       verbose: bool = True                     # Print progress info
       oxr_handles: Optional[...] = None        # External OpenXR handles (optional)
       mcap_config: Optional[...] = None        # Required for REPLAY, optional for LIVE

When ``mode`` is ``SessionMode.REPLAY``, ``TeleopSession`` skips OpenXR
session creation and reads tracking data from the MCAP file specified in
``mcap_config`` (a ``McapReplayConfig``).  ``mcap_config`` is **required** in
replay mode — omitting it raises ``ValueError``.  In the default ``LIVE``
mode, ``mcap_config`` is optional; passing an ``McapRecordingConfig`` enables
recording to disk.  See :doc:`/references/mcap_record_replay` for full
details.

When ``oxr_handles`` is provided (live mode), ``TeleopSession`` uses the
supplied handles instead of creating its own OpenXR session. The caller is
responsible for the external session's lifetime. Construct handles with
``OpenXRSessionHandles(instance, session, space, proc_addr)`` where each
argument is a ``uint64`` handle value.

.. code-block:: python

   from teleopcore.oxr import OpenXRSessionHandles

   handles = OpenXRSessionHandles(
       instance_handle, session_handle, space_handle, proc_addr
   )
   config = TeleopSessionConfig(
       app_name="MyApp",
       pipeline=pipeline,
       oxr_handles=handles,  # Skip internal OpenXR session creation
   )

PluginConfig
^^^^^^^^^^^^

Configure plugins:

.. code-block:: python

   PluginConfig(
       plugin_name="controller_synthetic_hands",
       plugin_root_id="synthetic_hands",
       search_paths=[Path("/path/to/plugins")],
       enabled=True,
       plugin_args=["--arg1=val1", "--arg2=val2"],
   )

.. note::

   Any ``--plugin-root-id=...`` in ``plugin_args`` is ignored so that the
   ``plugin_root_id`` parameter cannot be overridden.

API Reference
-------------

TeleopSession
^^^^^^^^^^^^^

Methods
"""""""

- ``step(*, external_inputs=None, graph_time=None, execution_events=None) -> Dict[str, TensorGroup]``
  -- Execute one step: updates the DeviceIO session, polls tracker data, merges
  any caller-provided ``external_inputs``, and executes the retargeting pipeline.
  ``graph_time`` can be provided explicitly; when omitted, monotonic time is used
  for both sim/real time. If ``execution_events`` is provided, it is injected into
  ``ComputeContext`` and ``teleop_control_pipeline`` is skipped for that step.
  Raises ``ValueError`` if required external inputs are missing or collide with
  DeviceIO source names.
- ``get_external_input_specs() -> Dict[str, RetargeterIOType]`` -- Return the
  input specifications for all external (non-DeviceIO) leaf nodes that require
  caller-provided inputs in ``step()``.
- ``has_external_inputs() -> bool`` -- Whether this pipeline has external leaf
  nodes that require caller-provided inputs.
- ``get_elapsed_time() -> float`` -- Get elapsed time since session started.

Example (explicit GraphTime + ExecutionEvents override):

.. code-block:: python

   import time

   from isaacteleop.retargeting_engine.interface.execution_events import (
       ExecutionEvents,
       ExecutionState,
   )
   from isaacteleop.retargeting_engine.interface.retargeter_core_types import GraphTime

   now_ns = time.monotonic_ns()
   result = session.step(
       graph_time=GraphTime(sim_time_ns=123_000_000, real_time_ns=now_ns),
       execution_events=ExecutionEvents(
           execution_state=ExecutionState.PAUSED,
           reset=False,
       ),
   )

Properties
""""""""""

- ``frame_count: int`` -- Current frame number
- ``start_time: float`` -- Session start time
- ``config: TeleopSessionConfig`` -- The configuration object
- ``oxr_session: Optional[OpenXRSession]`` -- The internal OpenXR session, or
  ``None`` when using external handles (read-only)

Helper Functions
^^^^^^^^^^^^^^^^

The module also exports two utility functions:

- ``get_required_oxr_extensions_from_pipeline(pipeline) -> List[str]`` --
  Discover the OpenXR extensions needed by a retargeting pipeline by
  traversing its DeviceIO source leaf nodes. Returns a sorted, deduplicated
  list of extension name strings.

- ``create_standard_inputs(trackers) -> Dict[str, IDeviceIOSource]`` --
  Convenience function that creates ``HandsSource``, ``ControllersSource``,
  and/or ``HeadSource`` instances from a list of tracker objects.

Examples
--------

Complete Examples
^^^^^^^^^^^^^^^^^

#. **Simplified Gripper Example**: ``examples/retargeting/python/gripper_retargeting_simple.py``
   -- Shows the minimal configuration approach and demonstrates auto-creation
   of input sources.

Before vs After
^^^^^^^^^^^^^^^

**Before (verbose, manual setup):**

.. code-block:: python

   # Create trackers
   controller_tracker = deviceio.ControllerTracker()

   # Get extensions
   required_extensions = deviceio.DeviceIOSession.get_required_extensions([controller_tracker])

   # Create OpenXR session
   oxr_session = oxr.OpenXRSession.create("MyApp", required_extensions)
   oxr_session.__enter__()

   # Create DeviceIO session
   handles = oxr_session.get_handles()
   deviceio_session = deviceio.DeviceIOSession.run([controller_tracker], handles)
   deviceio_session.__enter__()

   # Setup plugins
   plugin_manager = pm.PluginManager([...])
   plugin_context = plugin_manager.start(...)

   # Setup pipeline
   controllers = ControllersSource(name="controllers")
   gripper = GripperRetargeter(name="gripper")
   pipeline = gripper.connect({...})

   # Main loop
   while True:
       deviceio_session.update()
       # Manual data injection needed for new sources
       left_controller = controller_tracker.get_left_controller(deviceio_session)
       right_controller = controller_tracker.get_right_controller(deviceio_session)
       inputs = {
           "controllers": {
               "deviceio_controller_left": [left_controller],
               "deviceio_controller_right": [right_controller]
           }
       }
       result = pipeline(inputs)
       # ... error handling, cleanup ...

**After (declarative):**

.. code-block:: python

   # Configuration
   config = TeleopSessionConfig(
       app_name="MyApp",
       trackers=[controller_tracker],
       pipeline=pipeline,
   )

   # Run!
   with TeleopSession(config) as session:
       while True:
           result = session.step()  # Everything handled automatically!

Benefits
--------

#. **Reduced Boilerplate** -- ~70% reduction in code length
#. **Declarative** -- Focus on configuration, not implementation
#. **Auto-Initialization** -- Plugins and sessions all managed automatically
#. **Self-Documenting** -- Configuration structure makes intent clear
#. **Error Handling** -- Automatic error handling and cleanup
#. **Plugin Management** -- Built-in plugin lifecycle management
#. **Maintainable** -- Changes to setup logic happen in one place

Advanced Features
-----------------

Custom Update Logic
^^^^^^^^^^^^^^^^^^^

.. code-block:: python

   with TeleopSession(config) as session:
       while True:
           result = session.step()

           # Custom logic
           left_gripper = result["gripper_left"][0]
           if left_gripper > 0.5:
               print("Left gripper activated!")

           # Frame timing
           if session.frame_count % 60 == 0:
               print(f"Running at {60 / session.get_elapsed_time():.1f} FPS")
