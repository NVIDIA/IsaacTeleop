"""TeleopCore - Teleoperation Core Library

This package provides Python bindings for teleoperation with Extended Reality I/O.
"""

__version__ = "1.0.0"

# Import submodules
from . import xrio
from . import oxr

__all__ = ["xrio", "oxr", "__version__"]

