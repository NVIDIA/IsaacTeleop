<!-- SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved. -->
<!-- SPDX-License-Identifier: Apache-2.0 -->

# CloudXR — check, start, stop

Use the service CLI. It owns the lifecycle, refuses to clobber a live session, and cleans up
after itself. Every hand-rolled `pkill` / `rm` recipe below the fold exists only because older
builds had no CLI — do not reach for them first.

```bash
python -m isaacteleop.cloudxr.service status          # non-zero when nothing is serving
python -m isaacteleop.cloudxr.service start --accept-eula   # detached; survives your shell
python -m isaacteleop.cloudxr.service stop            # tears the runtime down with it
```

| Subcommand | What it does |
|---|---|
| `status` | Reports the running session — device profile, log files, client URL, detached or foreground. **Exits non-zero when no runtime is serving, so scripts gate on it.** Reports the session actually running, recovered from the service's own command line — not the defaults of the command you typed. |
| `start` | Starts detached; keeps running after the shell exits. **Refuses if a runtime is already serving** rather than dropping the live session. |
| `run` | Foreground until `Ctrl+C`. |
| `stop` | Stops the detached service and tears the runtime down. **Exits cleanly when there is nothing to stop.** |
| `logs` | The detached service's log (`-n` lines, `-f` to follow). |

So the whole gate is one command:

```bash
python -m isaacteleop.cloudxr.service status \
  || python -m isaacteleop.cloudxr.service start --accept-eula
```

- `--accept-eula` is required non-interactively, or it blocks on a prompt.
- `NV_DEVICE_PROFILE=Quest3` makes it **headless** — a device profile substitutes for a real
  headset. That is this repo's default; no headset needed.
- A GPU is required at run time (`--gpus all`); staging and installing need none.
- After it is up, source the env the output names: `~/.cloudxr/run/cloudxr.env`.

## Version check first

`python -m isaacteleop.cloudxr` (no `.service`) is the **deprecated** form. It still works and is
equivalent to `service run`, warns on startup, and **is removed in Isaac Teleop 1.7**.

Not every checkout has the service module yet. If `python -m isaacteleop.cloudxr.service status`
fails with `No module named`, you are on an older build — fall back to the section below.

## Fallback for builds without the service CLI

Start in the foreground and wait on **two** markers, the sentinel *and* the socket:

```bash
NV_DEVICE_PROFILE=Quest3 nohup python -u -m isaacteleop.cloudxr --accept-eula &
for _ in $(seq 1 120); do
  [ -f ~/.cloudxr/run/runtime_started ] && [ -S ~/.cloudxr/run/ipc_cloudxr ] && break
  sleep 0.5
done
source ~/.cloudxr/run/cloudxr.env
```

From Python: `wait_for_runtime_ready_sync()` polls the same sentinel, and
`with CloudXRLauncher.launch_context(args) as launcher:` tears both processes down on exit.

**Not `cloudxr.env`.** It is written ~0.5 s in, *before* the runtime is serving. Waiting on it
returns a false ready and the plugin then fails to connect.

To stop, signal the **supervisor** you started — `CloudXRLauncher.__exit__` shuts down the WSS
proxy and SIGTERMs the runtime's process group, escalating to SIGKILL on timeout. Two processes
are normal: the supervisor and its runtime child. `cloudxr.pid` holds the *child's* pid, so
`kill $(cat cloudxr.pid)` leaves the supervisor running.

## Traps

**An empty `~/.cloudxr` does not mean CloudXR is missing.** The runtime ships inside the
isaacteleop wheel (`isaacteleop/cloudxr/native/`); the first launch copies
`libopenxr_cloudxr.so` + `openxr_cloudxr.json` into `~/.cloudxr`. Probing for that json before
ever launching reports a false "not available" — one UMI run skipped every runtime stage this
way. Use `service status`, not file existence. Build the agent image with `WITH_CLOUDXR=1` to
pre-stage the files (it still never auto-starts).

**Never `pkill -f cloudxr`.** The pattern matches the *shell's own command line*, so the shell
kills itself: exit 143, no output, and the runtime often survives. Anything chained after it
never runs. One run lost ~10 turns to this, concluding the CLI was broken when it was fine. Use
`service stop`. If you must pattern-match on an old build, bracket the first letter:
`pkill -f "[i]saacteleop.cloudxr"`.

**Never `rm` the markers of a runtime you did not start.** Deleting `runtime_started` or
`ipc_cloudxr` does not stop the process — it hides a healthy runtime from every later probe,
including your own. If you do tear down by hand, re-assert the EULA marker afterwards
(`: > ~/.cloudxr/run/eula_accepted`) or the restart dies with "EULA not accepted".

**A failing script is not evidence the runtime is bad.** Check `service status` before restarting
anything.

## Errors

**`Environment variable NV_CXR_RUNTIME_DIR is not set`**
A plugin was started without the CloudXR env.
→ `source ~/.cloudxr/run/cloudxr.env` first. For a non-pushing subcommand (e.g.
`calibrate`), `ISAAC_TELEOP_DISABLE_CXR_ENV_CHECKS` skips the check.

**`Failed to get OpenXR system: -35 (XR_ERROR_FORM_FACTOR_UNAVAILABLE)`**
An inject plugin started before the headset connected. → `wait_for_system=true`; see
*Inject implementation* in `../phases/2-build-device.md`.
