"""avatar_pb2_loader — import-safe bridge for protobuf message types.

Tries the protoc-generated ``avatar_pb2`` module first (requires
``google.protobuf``).  When protobuf is not available (e.g. deb / SDK
distribution), re-exports the wire-compatible C++ pybind types from
``avatar_sdk.avatar_sdk`` so that ``ParseFromString``, ``SerializeToString``,
and attribute access all work without any extra dependency.

Usage (all consumers should go through this loader)::

    from avatar_sdk import avatar_pb2          # __init__ aliases this loader
    frame = avatar_pb2.AvatarDataFrame()
    frame.ParseFromString(raw_bytes)
"""

try:
    from .avatar_pb2 import (  # noqa: F401
        DESCRIPTOR,
        Stamp,
        Header,
        Joint,
        Point,
        Quaternion,
        Vector3,
        Pose,
        Hand,
        HandSkeleton,
        AvatarDataFrame,
    )
except ImportError:
    from .avatar_sdk import (  # noqa: F401
        Stamp,
        Header,
        Joint,
        Point,
        Quaternion,
        Vector3,
        Pose,
        Hand,
        HandSkeleton,
        AvatarDataFrame,
    )
