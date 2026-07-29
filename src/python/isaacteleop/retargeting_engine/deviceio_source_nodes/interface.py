# SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""
DeviceIO Source Node Interface.

DeviceIO source nodes are stateless converters that transform raw DeviceIO
flatbuffer data into standard retargeting engine tensor formats.
"""

from abc import abstractmethod
from typing import Any, Optional, TYPE_CHECKING

from ..interface.base_retargeter import BaseRetargeter
from ..interface.retargeter_core_types import RetargeterIO

if TYPE_CHECKING:
    from isaacteleop.deviceio import ITracker, TrackerVendor


class IDeviceIOSource(BaseRetargeter):
    """
    Interface for DeviceIO source nodes.

    Extends BaseRetargeter to add DeviceIO tracker discovery and polling.

    DeviceIO source nodes are retargeters that:
    - Take DeviceIO tracked wrappers as input (DeviceIOHeadPoseTracked, DeviceIOHandPoseTracked, etc.)
    - Convert them to standard retargeting engine tensor formats (HeadPose, HandInput, etc.)
    - Are pure converters with no internal state or session dependencies
    - Provide access to their associated tracker via get_tracker()
    - Know how to poll their own tracker via poll_tracker()

    This allows TeleopSession to:
    1. Discover required trackers via get_tracker()
    2. Initialize DeviceIO session with all trackers
    3. Poll each source for its own tracker data via poll_tracker()
    4. Map tracker data to correct input arguments via name
    5. Pass raw data as inputs to the retargeting pipeline
    6. Keep all session management in one place
    """

    def __init__(self, name: str, vendor: "Optional[TrackerVendor]" = None) -> None:
        """Initialize a DeviceIO source node.

        Args:
            name: Name identifier for this source node.
            vendor: Optional vendor selection for a vendored tracker (live mode
                only). Leave ``None`` for the tracker's default vendor. The vendor
                travels with the source so pipeline introspection (required OpenXR
                extensions) and session construction both resolve it directly from
                the pipeline, without a separate source-name-keyed config map.
        """
        super().__init__(name)
        self._vendor = vendor

    def get_vendor(self) -> "Optional[TrackerVendor]":
        """Get this source's vendor selection, or ``None`` for the tracker default.

        Used by TeleopSession and the extension-discovery helpers to build the
        DeviceIO ``VendorConfig`` for vendored trackers.
        """
        return self._vendor

    @abstractmethod
    def get_tracker(self) -> "ITracker":
        """Get the DeviceIO tracker associated with this source node.

        Used by TeleopSession for tracker discovery and initialization.

        Returns:
            The ITracker instance (e.g., HeadTracker, HandTracker, ControllerTracker)
        """
        pass

    @abstractmethod
    def poll_tracker(self, deviceio_session: Any) -> RetargeterIO:
        """Poll the tracker and return input data as a RetargeterIO dict.

        Each source knows its own tracker's API and its input_spec.
        Called by TeleopSession each frame to collect tracker data.

        Args:
            deviceio_session: The active DeviceIO session to poll from.

        Returns:
            Dict mapping input names to TensorGroups containing raw tracker data,
            matching this source's input_spec().
        """
        pass
