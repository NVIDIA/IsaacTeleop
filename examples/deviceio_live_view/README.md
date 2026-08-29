<!--
SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
SPDX-License-Identifier: Apache-2.0
-->

# DeviceIO Live View

Draws live DeviceIO human tracking — hands, head, controllers, full body — in the
browser with [viser](https://viser.studio). Trackers that are inactive or absent
are hidden rather than drawn in an error color. `CloudXRLauncher` starts the
CloudXR runtime and WSS proxy itself, so there is nothing to launch separately.

```bash
uv pip install -e ./examples/deviceio_live_view
python -m isaacteleop_examples.deviceio_live_view --accept-eula
```

Open the URL it prints (default <http://localhost:8080>). It binds every
interface, so another machine on the network can reach it at
`http://<this-host>:8080`; pass `--host 127.0.0.1` to keep it local, `--port` to
move it. Ctrl+C stops it.
