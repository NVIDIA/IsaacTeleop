# SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""
Thread-safe retargeter performance statistics.

Tracks timing information for compute, parameter sync, and visualization updates.
Thread-safe for concurrent access from main thread (updating) and UI thread (reading).
"""

import threading
import time
from typing import Dict


class RetargeterStats:
    """
    Thread-safe performance statistics for a retargeter.
    
    Automatically tracks:
    - Compute time (actual retargeting computation)
    - Parameter sync time (syncing parameters from UI)
    - Visualization update time (updating visualization state)
    
    Thread-safe for concurrent access from main thread (updating stats)
    and UI thread (reading stats for display).
    
    Example:
        stats = RetargeterStats("MyRetargeter")
        
        # Main thread updates (automatic in BaseRetargeter)
        with stats.time_compute():
            # ... compute code ...
            pass
        
        # UI thread reads (automatic in UI)
        snapshot = stats.get_snapshot()
        print(f"Compute: {snapshot['compute_ms']:.3f} ms")
    """
    
    def __init__(self, name: str):
        """
        Initialize retargeter stats.
        
        Args:
            name: Name of the retargeter (for display)
        """
        self._name = name
        self._lock = threading.Lock()
        
        # Timing stats in milliseconds (moving averages)
        self._compute_ms = 0.0
        self._param_sync_ms = 0.0
        self._viz_update_ms = 0.0
        
        # Instantaneous timing (last frame only)
        self._compute_ms_instant = 0.0
        self._viz_update_ms_instant = 0.0
        
        # Frame counter
        self._frame_count = 0
        
        # Moving average window (last N frames)
        self._window_size = 60  # 1 second at 60 Hz
        self._compute_history = []
        self._param_sync_history = []
        self._viz_update_history = []
    
    def time_compute(self):
        """Context manager for timing compute operations."""
        return _TimingContext(self, 'compute')
    
    def time_param_sync(self):
        """Context manager for timing parameter sync operations."""
        return _TimingContext(self, 'param_sync')
    
    def time_viz_update(self):
        """Context manager for timing visualization update operations."""
        return _TimingContext(self, 'viz_update')
    
    def _update_stat(self, stat_type: str, duration_ms: float):
        """Update a stat with new timing (internal, thread-safe)."""
        with self._lock:
            if stat_type == 'compute':
                self._compute_history.append(duration_ms)
                if len(self._compute_history) > self._window_size:
                    self._compute_history.pop(0)
                self._compute_ms = sum(self._compute_history) / len(self._compute_history)
                self._compute_ms_instant = duration_ms  # Also store instantaneous
                self._frame_count += 1
            elif stat_type == 'param_sync':
                self._param_sync_history.append(duration_ms)
                if len(self._param_sync_history) > self._window_size:
                    self._param_sync_history.pop(0)
                self._param_sync_ms = sum(self._param_sync_history) / len(self._param_sync_history)
            elif stat_type == 'viz_update':
                self._viz_update_history.append(duration_ms)
                if len(self._viz_update_history) > self._window_size:
                    self._viz_update_history.pop(0)
                self._viz_update_ms = sum(self._viz_update_history) / len(self._viz_update_history)
                self._viz_update_ms_instant = duration_ms  # Also store instantaneous
    
    def get_snapshot(self) -> Dict[str, any]:
        """
        Get thread-safe snapshot of current stats.
        
        Returns:
            Dictionary with timing statistics:
            - name: Retargeter name
            - compute_ms: Average compute time (ms)
            - param_sync_ms: Average parameter sync time (ms)
            - viz_update_ms: Average visualization update time (ms)
            - total_ms: Total average time (ms)
            - fps: Estimated frames per second
            - frame_count: Total frames processed
        """
        with self._lock:
            total_ms = self._compute_ms + self._param_sync_ms + self._viz_update_ms
            fps = 1000.0 / total_ms if total_ms > 0 else 0.0
            
            return {
                'name': self._name,
                'compute_ms': self._compute_ms,
                'param_sync_ms': self._param_sync_ms,
                'viz_update_ms': self._viz_update_ms,
                'compute_ms_instant': self._compute_ms_instant,
                'viz_update_ms_instant': self._viz_update_ms_instant,
                'total_ms': total_ms,
                'fps': fps,
                'frame_count': self._frame_count,
            }


class _TimingContext:
    """Internal context manager for timing operations."""
    
    def __init__(self, stats: RetargeterStats, stat_type: str):
        self._stats = stats
        self._stat_type = stat_type
        self._start_time = 0.0
    
    def __enter__(self):
        self._start_time = time.perf_counter()
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        duration_ms = (time.perf_counter() - self._start_time) * 1000.0
        self._stats._update_stat(self._stat_type, duration_ms)
        return False

