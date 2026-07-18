.. SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
.. SPDX-License-Identifier: Apache-2.0

OGLO Tactile Glove Plugin
=========================

C++ plugin that streams **OGLO** tactile gloves over BLE and records them through
the standard DeviceIO path. Each glove (one BLE device per hand) provides **80
tactile taxels** (5 fingers × 4×4) plus a **6-axis IMU** at 100 Hz. Source and
plugin README: :code-file:`src/plugins/oglo_tactile/README.md`.

This plugin follows the :doc:`add_device` pattern (FlatBuffer schema → plugin
``SchemaPusher`` → tracker → MCAP) and is modeled on the OAK camera plugin,
including its two recording modes.

.. contents:: On this page
   :local:
   :depth: 2

Components
----------

- **Schema** — :code-file:`src/core/schema/fbs/oglo_tactile.fbs`
  (``OgloGloveSample`` / ``OgloGloveSampleTracked`` / ``OgloGloveSampleRecord``).
- **Plugin** — :code-dir:`src/plugins/oglo_tactile` (BLE read → parse → push/record).
- **Tracker** — ``OgloTactileTracker``
  (:code-file:`src/core/deviceio_trackers/cpp/inc/deviceio_trackers/oglo_tactile_tracker.hpp`)
  with live backend ``LiveOgloTactileTrackerImpl``
  (:code-file:`src/core/live_trackers/cpp/live_oglo_tactile_tracker_impl.cpp`).

Build
-----

Linux only (BlueZ). The plugin is off by default.

.. code-block:: bash

   sudo apt install libdbus-1-dev          # BlueZ daemon + libdbus for the BLE backend
   cmake -B build -DBUILD_PLUGIN_OGLO=ON
   cmake --build build --target oglo_tactile_plugin --parallel

``nlohmann/json`` (MIT) is fetched automatically.

.. note::

   **BLE backend.** The plugin talks to BlueZ directly over `libdbus
   <https://www.freedesktop.org/wiki/Software/dbus/>`_ (AFL-2.1, permissive), so
   the build carries **no copyleft dependency** and works out of the box. The
   transport is isolated behind the ``OgloBleClient`` interface
   (:code-file:`src/plugins/oglo_tactile/ble/oglo_ble_client.hpp`), so an
   alternative backend can be dropped in via ``make_ble_client()`` without
   touching the parser, schema, or tracker.

Usage
-----

The plugin streams one glove (``--side``) and pushes it via OpenXR for a host
``OgloTactileTracker`` to record:

.. code-block:: bash

   # Push for a host OgloTactileTracker into a shared session MCAP
   ./build/src/plugins/oglo_tactile/oglo_tactile_plugin --side right --collection-prefix=oglo

The packet parser reads the device **Config characteristic** first and branches
on the notify ``flags`` byte (``0x04`` packed12 v5 — primary; ``0x02``/``0x01``
legacy schema-4 fallback), so payload sizes are never hardcoded.

Recorded data
-------------

The host ``OgloTactileTracker`` records per hand into channels
``oglo_<side>/oglo`` and ``oglo_<side>/oglo_tracked``, carrying
``core.OgloGloveSampleRecord``: ``seq``, ``device_time_us``, ``taxels[80]`` (raw
12-bit, ``finger,row,col``), and a 6-axis IMU, each with a ``DeviceDataTimestamp``
whose ``sample_time_local_common_clock`` is on the shared host monotonic clock —
so OGLO aligns in time with hand/head streams.

A complete data-collection demo (MetaQuest hand/head + both gloves + a live
in-headset tactile heatmap) lives at
:code-dir:`examples/oglo_tactile`; see its ``README.md``.

Tests
-----

``test_oglo_packet_parser`` validates the wire decode against the firmware's own
12-bit packing reference, plus the schema-4 fallback and malformed-packet
rejection:

.. code-block:: bash

   ctest --test-dir build -R oglo_packet_parser --output-on-failure
