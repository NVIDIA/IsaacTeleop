Device Trackers
===============

Trackers (defined in :code-dir:`src/core/deviceio`) are the consumer-side API for reading device
data from an active :code-file:`DeviceIOSession <src/core/deviceio/cpp/inc/deviceio/deviceio_session.hpp>`.
Each tracker manages one logical device, queries the OpenXR runtime every frame,
and exposes the latest sample through typed ``get_*()`` accessors.

There are two categories of trackers:

**OpenXR-direct trackers** -- read pose and input data through standard OpenXR
APIs (``xrLocateSpace``, ``xrSyncActions``, etc.):

- :code-file:`HeadTracker <src/core/deviceio/cpp/inc/deviceio/head_tracker.hpp>` -- HMD head pose
- :code-file:`HandTracker <src/core/deviceio/cpp/inc/deviceio/hand_tracker.hpp>` -- articulated hand joints (left and right)
- :code-file:`ControllerTracker <src/core/deviceio/cpp/inc/deviceio/controller_tracker.hpp>` -- controller poses and button/axis inputs (left and right)
- :code-file:`FullBodyTrackerPico <src/core/deviceio/cpp/inc/deviceio/full_body_tracker_pico.hpp>` -- 24-joint full body pose (PICO ``XR_BD_body_tracking``)

**SchemaTracker-based trackers** -- create new device type by defining a FlatBuffer schema and
reading it from OpenXR tensor collections via the
:code-file:`SchemaTracker <src/core/deviceio/cpp/inc/deviceio/schema_tracker.hpp>` utility.

- :code-file:`FrameMetadataTrackerOak <src/core/deviceio/cpp/inc/deviceio/frame_metadata_tracker_oak.hpp>` -- per-stream frame metadata from OAK cameras
- :code-file:`Generic3AxisPedalTracker <src/core/deviceio/cpp/inc/deviceio/generic_3axis_pedal_tracker.hpp>` -- foot pedal axis values

All trackers follow the same lifecycle:

1. Construct the tracker.
2. Pass it (along with any other trackers) to ``DeviceIOSession::run()``.
3. Call ``session.update()`` each frame.
4. Read data with the tracker's ``get_*()`` method.

.. note::

    The ``DeviceIOSession`` is considered a low-level API. In practice, it is recommended to
    use the :doc:`../getting_started/teleop_session` to manage a teleop session with multiple
    device trackers and retargeters to work together.

.. _data-schema-convention:

Data Schema Convention
----------------------

Every tracker's data is defined by a FlatBuffers schema under
:code-dir:`src/core/schema/fbs`. Each schema follows a three-tier convention:

.. code-block:: idl

   // 1. Inner data table -- the actual payload
   table Xxx {
       field_a: SomeType (id: 0);
       field_b: AnotherType (id: 1);
   }

   // 2. Tracked wrapper -- used by the in-memory tracker API.
   //    data is null when the tracked entity is inactive.
   table XxxTracked {
       data: Xxx (id: 0);
   }

   // 3. Record wrapper -- used as the MCAP recording root type.
   //    Adds a DeviceDataTimestamp alongside the payload.
   table XxxRecord {
       data: Xxx (id: 0);
       timestamp: DeviceDataTimestamp (id: 1);
   }

   root_type XxxRecord;

- **Inner data table** (e.g. ``HeadPose``, ``HandPose``, ``ControllerSnapshot``) --
  contains the device-specific fields. All fields are present when the parent
  wrapper's ``data`` pointer is non-null.

- **Tracked wrapper** (e.g. ``HeadPoseTracked``) -- wraps the inner data in an
  optional ``data`` field. The in-memory ``get_*()`` accessors return a reference
  to this wrapper. When ``data`` is ``nullptr`` (C++) or ``None`` (Python), the
  device is inactive or no sample has arrived yet.

- **Record wrapper** (e.g. ``HeadPoseRecord``) -- wraps the inner data plus a
  ``DeviceDataTimestamp``. This is the ``root_type`` written to MCAP channels by
  the recorder via ``serialize_all()``.

Shared Types
~~~~~~~~~~~~

**DeviceDataTimestamp** (:code-file:`src/core/schema/fbs/timestamp.fbs`)

All timestamp fields are ``int64`` nanoseconds.

.. list-table::
   :header-rows: 1
   :widths: 40 60

   * - Field
     - Description
   * - ``available_time_local_common_clock``
     - System monotonic time when the sample became available to the recording
       system. Useful for measuring pipeline latency.
   * - ``sample_time_local_common_clock``
     - System monotonic time when the sample was captured. Enables
       cross-device synchronization (values from different devices share the
       same clock domain).
   * - ``sample_time_raw_device_clock``
     - Timestamp from the device's own clock. Values from different devices
       are **not** directly comparable.

**Pose** (:code-file:`src/core/schema/fbs/pose.fbs`)

.. code-block:: idl

   struct Point      { x: float; y: float; z: float; }
   struct Quaternion  { x: float; y: float; z: float; w: float; }
   struct Pose {
     position: Point;       // meters
     orientation: Quaternion;
   }

.. _tracker-reference:

Tracker Reference
-----------------

HeadTracker
~~~~~~~~~~~

Tracks the HMD head pose via the OpenXR view space.

- Schema: :code-file:`src/core/schema/fbs/head.fbs`
- C++ header: ``#include <deviceio/head_tracker.hpp>``
- Python import: ``from isaacteleop.deviceio import HeadTracker``
- Record channels: ``head`` | MCAP schema: ``core.HeadPoseRecord``
- Tests:

  - :code-file:`src/core/schema_tests/cpp/test_head.cpp`
  - :code-file:`src/core/schema_tests/python/test_head.py`

- Examples:

  - :code-file:`examples/oxr/cpp/oxr_simple_api_demo.cpp`
  - :code-file:`examples/oxr/python/modular_example.py`

HandTracker
~~~~~~~~~~~

Tracks articulated hand joints (26 joints per hand, following the OpenXR
``XrHandJointEXT`` ordering) using the ``XR_EXT_hand_tracking`` extension.

- Schema: :code-file:`src/core/schema/fbs/hand.fbs`
- C++ header: ``#include <deviceio/hand_tracker.hpp>``
- Python import: ``from isaacteleop.deviceio import HandTracker``
- Record channels: ``left_hand``, ``right_hand`` | MCAP schema: ``core.HandPoseRecord``
- Tests:

  - :code-file:`src/core/schema_tests/cpp/test_hand.cpp`
  - :code-file:`src/core/schema_tests/python/test_hand.py`
  - :code-file:`examples/oxr/python/test_synthetic_hands.py`

- Examples:

  - :code-file:`examples/oxr/cpp/oxr_simple_api_demo.cpp`
  - :code-file:`examples/oxr/python/modular_example.py`
  - :code-file:`examples/retargeting/python/sources_example.py`

ControllerTracker
~~~~~~~~~~~~~~~~~

Tracks both left and right controllers -- grip and aim poses, plus button and
axis inputs. Uses standard OpenXR action bindings.

- Schema: :code-file:`src/core/schema/fbs/controller.fbs`
- C++ header: ``#include <deviceio/controller_tracker.hpp>``
- Python import: ``from isaacteleop.deviceio import ControllerTracker``
- Record channels: ``left_controller``, ``right_controller`` | MCAP schema: ``core.ControllerSnapshotRecord``
- Tests:

  - :code-file:`src/core/schema_tests/cpp/test_controller.cpp`
  - :code-file:`src/core/schema_tests/python/test_controller.py`
  - :code-file:`examples/oxr/python/test_controller_tracker.py`

- Examples:

  - :code-file:`examples/retargeting/python/sources_example.py`
  - :code-file:`examples/teleop/python/locomotion_retargeting_example.py`
  - :code-file:`examples/teleop/python/gripper_retargeting_example_simple.py`

FullBodyTrackerPico
~~~~~~~~~~~~~~~~~~~

Tracks 24 body joints on PICO devices using the ``XR_BD_body_tracking``
extension.

- Schema: :code-file:`src/core/schema/fbs/full_body.fbs`
- C++ header: ``#include <deviceio/full_body_tracker_pico.hpp>``
- Python import: ``from isaacteleop.deviceio import FullBodyTrackerPico``
- Record channels: ``full_body`` | MCAP schema: ``core.FullBodyPosePicoRecord``
- Tests:

  - :code-file:`src/core/schema_tests/cpp/test_full_body.cpp`
  - :code-file:`src/core/schema_tests/python/test_full_body.py`
  - :code-file:`examples/oxr/python/test_full_body_tracker.py`

FrameMetadataTrackerOak
~~~~~~~~~~~~~~~~~~~~~~~

Multi-channel tracker for per-frame metadata from OAK camera streams.
Uses the :code-file:`SchemaTracker <src/core/deviceio/cpp/inc/deviceio/schema_tracker.hpp>`
utility internally.

- Schema: :code-file:`src/core/schema/fbs/oak.fbs`
- C++ header: ``#include <deviceio/frame_metadata_tracker_oak.hpp>``
- Python import: ``from isaacteleop.deviceio import FrameMetadataTrackerOak``
- Record channels: one per configured stream (e.g. ``Color``, ``MonoLeft``) | MCAP schema: ``core.FrameMetadataOakRecord``
- Tests:

  - :code-file:`src/core/schema_tests/cpp/test_oak.cpp`
  - :code-file:`src/core/schema_tests/python/test_camera.py`
  - :code-file:`examples/oxr/python/test_oak_camera.py`

- Examples:

  - :code-file:`examples/schemaio/frame_metadata_printer.cpp`

Generic3AxisPedalTracker
~~~~~~~~~~~~~~~~~~~~~~~~

Reads foot pedal axis values pushed by a device plugin through OpenXR tensor
collections. Uses the :code-file:`SchemaTracker <src/core/deviceio/cpp/inc/deviceio/schema_tracker.hpp>`
utility internally.

- Schema: :code-file:`src/core/schema/fbs/pedals.fbs`
- C++ header: ``#include <deviceio/generic_3axis_pedal_tracker.hpp>``
- Python import: ``from isaacteleop.deviceio import Generic3AxisPedalTracker``
- Record channels: ``pedals`` | MCAP schema: ``core.Generic3AxisPedalOutputRecord``
- Tests:

  - :code-file:`src/core/schema_tests/cpp/test_pedals.cpp`
  - :code-file:`src/core/schema_tests/python/test_pedals.py`

- Examples:

  - :code-file:`examples/schemaio/pedal_printer.cpp`
  - :code-file:`examples/teleop/python/foot_pedal_locomotion_example.py`

.. note::

   The Python method is named ``get_pedal_data()`` (instead of the C++
   ``get_data()``).

.. _tracker-usage-example:

Usage Examples
--------------

For end-to-end usage patterns combining trackers with a ``DeviceIOSession``, see:

- **C++**: :code-file:`examples/oxr/cpp/oxr_simple_api_demo.cpp`
- **Python**: :code-file:`examples/oxr/python/modular_example.py`

For higher-level usage with the teleop session manager and retargeting, see:

- :code-file:`examples/retargeting/python/sources_example.py`
- :code-file:`examples/teleop/python/gripper_retargeting_example_simple.py`
- :code-file:`examples/teleop/python/locomotion_retargeting_example.py`
