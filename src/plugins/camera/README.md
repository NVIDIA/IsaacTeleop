# Camera Plugins

Modular camera plugin framework for capturing and recording video from various camera sources.

## Structure

```
camera/
├── core/              # Shared library: CameraPlugin, RawDataWriter, configs
├── inc/core/          # Shared headers
├── oakd/              # OAK-D camera plugin (see oakd/README.md)
└── (future: realsense/, zed/, etc.)
```

## Shared Components (core/)

- **CameraPlugin**: Plugin lifecycle management, threading, OpenXR integration
- **RawDataWriter**: Raw H.264 file writer (Annex B format)
- **ICamera**: Interface for camera implementations
- **CameraConfig/RecordConfig**: Configuration structures

## Adding a New Camera Plugin

1. Create a new subdirectory (e.g., `realsense/`)
2. Implement the `ICamera` interface
3. Create a `plugin.yaml` manifest
4. Add a `CMakeLists.txt` that builds your plugin and links to `camera_plugin_core`
5. Add `add_subdirectory(realsense)` to the parent CMakeLists.txt

See `oakd/` for a complete example.

## Dependencies

- **Camera-specific SDKs**: Each plugin manages its own SDK (e.g., DepthAI for OAK-D)
