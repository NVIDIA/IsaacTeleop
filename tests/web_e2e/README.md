<!--
SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
SPDX-License-Identifier: Apache-2.0
-->

# Web Client End-to-End Tests

Playwright spec that drives the prebuilt `webxr_client` against a live CloudXR
runtime.

## What it verifies

[`cloudxr-connect.spec.ts`](./cloudxr-connect.spec.ts) navigates the web client
with `?serverIP=<host>&port=<port>`, then asserts:

1. SDK initialized (`#errorMessageText` says `"CloudXR.js SDK is supported."`).
2. CONNECT button enabled and clickable.
3. `#startButton` flips to `"CONNECT (XR session active)"` — IWER mock
   `requestSession()` resolved.
4. **A WebSocket frame is received from the runtime** (via
   `page.on('websocket')` + `framereceived`) — proof of an actual round-trip,
   not just a client-side IWER session.
5. Session label remains stable for 3 s (no torn handshake).

No `webxr_client` source / test-hook changes; everything reads existing DOM
plus the standard browser `WebSocket` API.

## How CI runs it

Three jobs in [`.github/workflows/build-ubuntu.yml`](../../.github/workflows/build-ubuntu.yml):

1. `build-ubuntu` — produces `isaacteleop-install-release-x64-py3.11`.
2. `build-webapp` — `npm run build` in `webxr_client/`, produces
   `webxr-client-build`.
3. `test-cloudxr-web-e2e` — runs on `[self-hosted, linux, gpu, x64]`,
   downloads both artifacts and executes
   [`scripts/run_test_e2e_with_web.sh`](../../scripts/run_test_e2e_with_web.sh),
   which `docker compose up`s
   [`docker-compose.test-e2e.yaml`](../../deps/cloudxr/docker-compose.test-e2e.yaml)
   (cloudxr-runtime + playwright on a project bridge network), waits for
   health, runs the spec, tears down. `publish-wheel` gates on this job.

Project-scoped (`docker compose -p ...-${GITHUB_RUN_ID}-...`) and
Docker-managed named volumes — safe for parallel runs on one GPU host.

## Run locally

Requires a reachable CloudXR runtime. Easiest path on macOS or any Linux box
without GPU passthrough:

```bash
# 1. Serve the webapp (dev-server is fine — pick one).
( cd deps/cloudxr/webxr_client && npm install && npm run dev-server ) &
# Or, to mirror CI exactly:
#   ( cd deps/cloudxr/webxr_client && npm install && npm run build )
#   ( cd deps/cloudxr/webxr_client/build && python3 -m http.server 8080 ) &

# 2. Run the spec (host bundled Chromium, not the compose container).
cd tests/web_e2e
npm install && npx playwright install chromium

WEB_URL=http://localhost:8080 \
CXR_HOST=<runtime-host-or-ip> \
CXR_PORT=49100 \
  npx playwright test --reporter=list
```

For the full CI-equivalent flow (Linux + NVIDIA GPU + nvidia-container-toolkit
required):

```bash
export CXR_WEBAPP_DIR="$PWD/deps/cloudxr/webxr_client/build"
./scripts/run_test_e2e_with_web.sh
```

## Env vars

| Var | Default | Purpose |
|---|---|---|
| `WEB_URL` | `http://cloudxr-runtime:8080` | Page baseURL for `page.goto()`. |
| `CXR_HOST` | `cloudxr-runtime` | Address the browser dials over ws://. |
| `CXR_PORT` | `49100` | Direct CloudXR signaling port (plain ws://). |
| `PW_CHANNEL` | _(unset)_ | Optional: `chrome`, `msedge`, etc., to use a system browser. |

## Useful flags

```bash
npx playwright test --headed              # watch the browser
npx playwright test --ui                  # interactive runner
npx playwright show-trace test-results/.../trace.zip   # post-mortem
```
