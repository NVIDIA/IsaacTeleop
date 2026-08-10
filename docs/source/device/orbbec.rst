.. SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
.. SPDX-License-Identifier: Apache-2.0

Orbbec Ego camera
==================

The Orbbec Ego plugin supports its two color sensors, accelerometer, gyroscope, microphone, calibration, controls, device state, local MCAP, and TeleopSession synchronized MCAP. The default ``metadata-only`` MCAP mode keeps raw MJPEG/H.264/H.265 and 48 kHz mono S16_LE WAV as sidecars and stores their synchronization metadata. Optional ``--mcap-media=embedded`` stores the validated encoded video access units and PCM audio blocks in the MCAP itself; it does not transcode them. Ego PID ``0x1201`` exposes no Depth/IR sensors, so depth, D2C, IR, and point-cloud functions are not offered.

For a source checkout, start with ``src/plugins/orbbec/orbbec_ego.sh``: its ``doctor`` command checks prerequisites without using sudo, ``build`` configures only this plugin, ``capabilities`` prints the connected device capabilities, and ``record`` creates a timestamped verified recording directory. The default recording remains ``metadata-only`` for sidecar-media compatibility; ``embedded`` is an explicit optional mode. Build with ``-DBUILD_PLUGIN_ORBBEC_CAMERA=ON`` and ``-DORBBEC_SDK_ROOT=/path/to/OrbbecSDK``. Install the SDK udev rules and use a direct, reliable USB data connection. Ego PID ``0x1201`` enumerates as USB 2.0 (``bcdUSB 2.00`` / ``480M``) by design, even on a USB 3.x host port; use ``camera_plugin_orbbec --list-capabilities`` for the connected device's exact profiles and property ranges.

Three recording modes are available: omit metadata flags for raw media only, use ``--mcap-filename`` for plugin-local metadata, or use ``--collection-prefix`` with ``FrameMetadataTrackerOrbbec``, ``OrbbecImuTracker``, ``OrbbecAudioTracker``, ``OrbbecCalibrationTracker``, and ``OrbbecDeviceStateTracker`` in a TeleopSession. The two MCAP flags are mutually exclusive.

See the `Orbbec Ego plugin README <https://github.com/NVIDIA/IsaacTeleop/blob/main/src/plugins/orbbec/README.md>`_ for prerequisites, configuration, build/install commands, raw-media and MCAP modes, TeleopSession integration, controls, conversion, troubleshooting, and the independent ``camera_viz`` GPU stereo source.
