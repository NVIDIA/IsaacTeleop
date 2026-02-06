# SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""
DeviceIO Source Node Interface.

DeviceIO source nodes are stateless converters that transform raw DeviceIO
flatbuffer data into standard retargeting engine tensor formats.
"""

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from isaacteleop.deviceio import ITracker


class IDeviceIOSource(ABC):
    """
    Interface for DeviceIO source nodes.
    
    DeviceIO source nodes are stateless retargeters that:
    - Take DeviceIO flatbuffer objects as input (DeviceIOHeadPose, DeviceIOHandPose, etc.)
    - Convert them to standard retargeting engine tensor formats (HeadPose, HandInput, etc.)
    - Are pure converters with no internal state or session dependencies
    - Provide access to their associated tracker via get_tracker()
    - Expose their name for input argument mapping
    
    This allows TeleopSession to:
    1. Discover required trackers via get_tracker()
    2. Initialize DeviceIO session with all trackers
    3. Manually poll DeviceIO trackers
    4. Map tracker data to correct input arguments via name property
    5. Pass raw data as inputs to the retargeting pipeline
    6. Keep all session management in one place
    """
    
    @property
    @abstractmethod
    def name(self) -> str:
        """Get the name of this source node.
        
        Used by TeleopSession to map tracker data to pipeline input arguments.
        
        Returns:
            The unique name of this source node
        """
        pass
    
    @abstractmethod
    def get_tracker(self) -> "ITracker":
        """Get the DeviceIO tracker associated with this source node.
        
        Used by TeleopSession for tracker discovery and initialization.
        
        Returns:
            The ITracker instance (e.g., HeadTracker, HandTracker, ControllerTracker)
        """
        pass

