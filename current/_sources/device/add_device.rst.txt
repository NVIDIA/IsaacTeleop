Add a New Device
================

To add a new device that streams typed data over the OpenXR runtime, follow these four steps.
The reference implementation is the **generic 3-axis foot pedal**:

.. list-table::
   :header-rows: 1
   :widths: 18 82

   * - Component
     - Code Location
   * - Data Schema
     - :code-file:`src/core/schema/fbs/pedals.fbs`
   * - Device Plugin
     - :code-dir:`src/plugins/generic_3axis_pedal`
   * - Device Tracker
     - :code-file:`src/core/deviceio/cpp/generic_3axis_pedal_tracker.cpp`
   * - Debug printer
     - :code-file:`examples/schemaio/pedal_printer.cpp`


Step 1: Define the data schema
------------------------------

Define a FlatBuffer schema (`.fbs`) under :code-dir:`src/core/schema/fbs`. The schema drives both
serialization in the plugin and deserialization in the tracker; pusher and reader must agree
on the same schema ahead of time (the schema is not sent over the wire).

Reference schema: :code-file:`src/core/schema/fbs/pedals.fbs`

.. code-block:: idl
   :class: code-100col

   include "point.fbs";
   include "timestamp.fbs";

   namespace core;

   table Generic3AxisPedalOutput {
     left_pedal: float (id: 0);
     right_pedal: float (id: 1);
     rudder: float (id: 2);
   }

   table Generic3AxisPedalOutputRecord {
     data: Generic3AxisPedalOutput (id: 0);
     timestamp: DeviceDataTimestamp (id: 1);
   }

- **Output table** — The primary payload type (e.g. ``Generic3AxisPedalOutput``) with the
  device fields. This is what the plugin serializes and pushes.
- **Tracked wrapper** — A table that wraps the output in an optional ``data`` field
  (e.g. ``Generic3AxisPedalOutputTracked``). Used by the in-memory tracker API so that
  ``data`` can be null when no sample is available.
- **Record wrapper** — A table that wraps the output plus ``DeviceDataTimestamp``
  (e.g. ``Generic3AxisPedalOutputRecord``). This is the root type written to MCAP channels
  by the recorder; trackers serialize into this type in ``serialize_all()``.
- **root_type** — Set to the Record type (e.g. ``root_type Generic3AxisPedalOutputRecord;``).

Include ``timestamp.fbs`` for ``DeviceDataTimestamp``; include other shared types (e.g.
``point.fbs``) as needed. After adding or changing a schema, rebuild so that the C++ and
Python generated code (e.g. ``pedals_generated.h``, ``pedals_bfbs_generated.h``) is updated.

Step 2: Implement a device plugin
---------------------------------

The plugin runs in a separate process (or as part of a host app), reads hardware, and pushes
serialized FlatBuffer data via OpenXR using the **SchemaPusher** from the ``pusherio`` library.
Reuse the same pattern as the example apps in ``examples/schemaio/`` (e.g. ``pedal_pusher``
which uses ``SchemaPusher``).

- **OpenXR session** — Create an ``OpenXRSession`` with extensions from
  ``SchemaPusher::get_required_extensions()`` (includes ``XR_NVX1_push_tensor`` and
  ``XR_NVX1_tensor_data``).
- **SchemaPusher** — Construct a ``SchemaPusher`` with ``OpenXRSessionHandles`` and a
  ``SchemaPusherConfig``: ``collection_id``, ``max_flatbuffer_size``, ``tensor_identifier``,
  ``localized_name``, and optionally ``app_name``. The ``collection_id`` and
  ``tensor_identifier`` must match what the tracker uses.
- **Push loop** — In your update loop, fill the schema's native type (e.g.
  ``Generic3AxisPedalOutputT``), serialize it with ``FlatBufferBuilder`` and the generated
  ``Pack()``, then call ``pusher_.push_buffer(ptr, size, sample_time_local_common_clock_ns,
  sample_time_raw_device_clock_ns)``. Use a monotonic clock (e.g. ``core::os_monotonic_now_ns()``)
  for the local common clock; use the device's own clock for the raw device clock if available.

Reference implementation: :code-dir:`src/plugins/generic_3axis_pedal`. The plugin holds a
``core::SchemaPusher`` member, opens the Linux joystick device, maps axes to
``Generic3AxisPedalOutputT``, and calls ``push_current_state()`` from ``update()``. See
:code-file:`generic_3axis_pedal_plugin.hpp <src/plugins/generic_3axis_pedal/generic_3axis_pedal_plugin.hpp>` and
:code-file:`generic_3axis_pedal_plugin.cpp <src/plugins/generic_3axis_pedal/generic_3axis_pedal_plugin.cpp>`.

Step 3: Implement a tracker
----------------------------

The tracker runs inside a consumer process (e.g. Teleop pipeline or a small reader app). It
implements the **ITracker** interface and uses **SchemaTracker** (from the ``deviceio`` library)
to read raw tensor samples from OpenXR. Implement a concrete tracker class (e.g.
``Generic3AxisPedalTracker``) that:

- **Extends ITracker** — Override ``get_required_extensions()``, ``get_name()``,
  ``get_schema_name()``, ``get_schema_text()``, and ``get_record_channels()``. Return
  ``SchemaTracker::get_required_extensions()`` for extensions; return the Record type name
  and binary schema for MCAP; return at least one channel name.
- **Holds SchemaTrackerConfig** — Same logical fields as the pusher: ``collection_id``,
  ``max_flatbuffer_size``, ``tensor_identifier``, ``localized_name``. Must match the plugin.
- **create_tracker()** — Return an ``ITrackerImpl`` that holds a ``SchemaTracker`` and
  implements ``update(XrTime)`` and ``serialize_all(channel_index, callback)``.

In the **Impl**:

- **update()** — Call ``m_schema_reader.read_all_samples(pending_records)``. If the
  collection is not present, clear the tracked state (e.g. set ``m_tracked.data = nullptr``).
  Otherwise, deserialize the latest sample (or all samples) into your tracked type and
  keep the last one for ``get_data()``.
- **serialize_all()** — For each sample in the pending batch, deserialize, build the
  Record FlatBuffer (output table + ``DeviceDataTimestamp``), and invoke the callback with
  ``(log_time_ns, buffer_ptr, size)``. The buffer is only valid during the callback. If the
  device disappeared and there are no samples, you may emit one record with null data and
  the update-tick timestamp so the MCAP stream marks absence.

Reference implementation: :code-file:`src/core/deviceio/cpp/generic_3axis_pedal_tracker.cpp`. It
composes ``SchemaTracker``, implements ``Impl::update()`` and ``Impl::serialize_all()``,
and exposes ``get_data(session)`` returning ``Generic3AxisPedalOutputTrackedT``. See also
:code-file:`inc/deviceio/schema_tracker.hpp <src/core/deviceio/cpp/inc/deviceio/schema_tracker.hpp>` for ``SchemaTracker`` and ``SampleResult`` (buffer +
timestamp).

Step 4: Implement a simple C++ printer (optional)
-------------------------------------------------

A minimal reader app verifies the full path: plugin (or pusher) pushes; printer discovers
the collection and prints samples. Pattern (see :code-file:`examples/schemaio/pedal_printer.cpp`):

1. Create the tracker (e.g. ``std::make_shared<Generic3AxisPedalTracker>(collection_id,
   max_flatbuffer_size)``).
2. Get required extensions with ``DeviceIOSession::get_required_extensions(trackers)`` and
   create an ``OpenXRSession``.
3. Create a ``DeviceIOSession`` with ``DeviceIOSession::run(trackers, oxr_session->get_handles())``.
4. Loop: call ``session->update()``, then read ``tracker->get_data(*session)``. If
   ``tracked.data`` is non-null, use the latest sample; otherwise sleep briefly and repeat.

Use the same ``collection_id`` (and optionally ``tensor_identifier``) as the plugin. See
:ref:`Schema IO example: build and run <schema-io-example>` above for building and running
``pedal_pusher`` and ``pedal_printer``.

.. _schema-io-example:

Schema IO example: build and run
--------------------------------

The **Schema IO example** is a simpler example that demonstrates pushing and reading serialized
FlatBuffer data via the OpenXR runtime using the Generic Tensor Collection interface.
It provides two binaries: **pedal_pusher** (serializes and pushes ``Generic3AxisPedalOutput`` using
``SchemaPusher``) and **pedal_printer** (reads via ``Generic3AxisPedalTracker`` and
``DeviceIOSession``). Both use the ``XR_NVX1_push_tensor`` and ``XR_NVX1_tensor_data`` extensions.
Pusher and reader agree on the schema (``Generic3AxisPedalOutput`` from ``pedals.fbs``), so the
schema is not sent over the wire.

**Build** (from the project root, with examples enabled):

.. code-block:: bash

   cmake -B build -DBUILD_EXAMPLES=ON
   cmake --build build --parallel
   cmake --install build

**Run** pusher and printer in separate terminals:

.. code-block:: bash

   # Terminal 1: Start printer
   ./install/examples/schemaio/pedal_printer

   # Terminal 2: Start pusher
   ./install/examples/schemaio/pedal_pusher

The printer discovers the tensor collection created by the pusher and prints received samples.
Both exit after 100 samples, or press Ctrl+C to exit early.

**Components**

- **SchemaPusher** (``pusherio`` library) — Pushes serialized FlatBuffer data via OpenXR tensor
  extensions: takes externally-provided OpenXR session handles, creates a tensor collection with
  the configured identifier, provides ``push_buffer()`` for raw serialized data. Use composition
  to create typed wrappers (e.g. ``Generic3AxisPedalPusher`` in :code-file:`examples/schemaio/pedal_pusher.cpp`).
- **SchemaTracker** (``deviceio`` library) — Base for reading FlatBuffer schema data via OpenXR:
  implements ``ITracker`` for use with ``DeviceIOSession``, discovers collections by identifier,
  exposes ``read_all_samples()``; subclasses implement ``update()`` to deserialize and
  ``serialize_all()`` to re-serialize typed data.
- **Generic3AxisPedalTracker** — Concrete tracker for ``Generic3AxisPedalOutput``: extends
  ``SchemaTracker`` with schema-specific deserialization and provides ``get_data()`` for the latest
  ``Generic3AxisPedalOutputT``.
- **DeviceIOSession** — Session manager: collects required OpenXR extensions from registered
  trackers, creates tracker implementations with session handles, and calls ``update()`` on all
  trackers during the update loop.
