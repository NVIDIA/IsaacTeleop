<!--
SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
SPDX-License-Identifier: Apache-2.0
-->

# Isaac Teleop Hub Client

This is the prototype Vite/React client for the Isaac Teleop Web 2.0 Hub.
It is served by the CloudXR WSS process at `/hub/` when the hub is enabled.

## Run with hot reload

In one terminal:

```sh
cd src/core/cloudxr/hub_client
npm ci
npm run dev
```

In another terminal, run the normal CloudXR entry point with the hub enabled
and point `/hub/` at the Vite dev server:

```sh
TELEOP_HUB_CLIENT_DEV_URL=http://localhost:5173/hub/ \
python -m isaacteleop.cloudxr --hub --host-client
```

Open `https://localhost:48322/` or `https://localhost:48322/hub/`. During
hot reload, the Python host redirects the hub page to
`http://localhost:5173/hub/`, while API and OOB requests proxy back to
`https://localhost:48322`.

## Run the prebuilt hub

The committed `build/` directory is the static bundle served at `/hub/`:

```sh
python -m isaacteleop.cloudxr --hub --host-client
```

Open `https://localhost:48322/hub/`. For a headset or another machine, use the
workstation address instead of `localhost`, for example
`https://<workstation-ip>:48322/hub/`.

## Refresh the prebuilt bundle

```sh
cd src/core/cloudxr/hub_client
npm ci
npm run typecheck
npm test
npm run build
```
