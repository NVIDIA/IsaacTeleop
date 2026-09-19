<!--
SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
SPDX-License-Identifier: Apache-2.0
-->

# Recording a take

One recording of a prescribed ten-step motion script, plus the label sidecar that
[the checker](checker/README.md) reads. A panel in your browser tells the performer
what to do; they press a button once they are in each pose.

**Linux only.** Recording drives the device through Isaac Teleop, which is a Linux
project — it is built and tested on Ubuntu and its wheel is `linux_x86_64`. There is no
macOS or Windows path to recording a take, and there is no plan for one. The checker
that reads the take back afterwards has no such constraint: it runs on Linux and macOS
alike, so a take recorded here can be verified anywhere.

You do not need to read any of the code under [`capture/`](capture), and nothing in
there is meant to be edited — see [Do not edit the script](#do-not-edit-the-script) at
the end.

## Before you start

- **The project built**, so that an `isaacteleop` wheel exists under `install/wheels/`
  or `build/wheels/`.
- **`uv`, `curl` and `unzip`** on the same Linux host.
- **`aplay`** — the spoken cues go through it. It comes from `alsa-utils`
  (`apt install alsa-utils` on Debian or Ubuntu). Install it before your first take: a
  missing `aplay` currently fails part way into the recording rather than at startup.
- **A headset with body tracking**, plus CloudXR installed (by default at `~/.cloudxr`).
  See [Get the headset streaming](#get-the-headset-streaming) below.
- **A performer who can stand up and follow spoken instructions.** Two people is easier
  than one — see the note about the space bar below.

## Set up, once per clone

Two scripts, in this order. The checker's comes first because it generates what the
panel reads the recording back with.

```bash
acceptance/full_body/checker/setup_env.sh
acceptance/full_body/capture/setup_env.sh
```

Both are idempotent and write nothing outside their own directory. Re-run them after
pulling.

## Get the headset streaming

Every `isaacteleop` command below runs under the interpreter `capture/setup_env.sh`
built. It is the only Python here that has the package — a bare `python` does not, and
on Ubuntu there is usually no `python` at all.

```bash
PY=acceptance/full_body/capture/.venv/bin/python
```

**Accept the CloudXR EULA, once per machine.** Review the licence, then

```bash
$PY -m isaacteleop.cloudxr.service run --accept-eula
```

Acceptance is remembered in `~/.cloudxr/run/eula_accepted`, so it is needed once per
install directory, not once per take.

**Start the service in a terminal of its own and leave it open.**

```bash
$PY -m isaacteleop.cloudxr.service run
```

`run` stays in the foreground and prints the runtime's log, so a headset that will not
connect says why where you are already looking; Ctrl+C stops it. `start` is the same
service detached, with `stop`, `status` and `logs` beside it. The runtime is a host
singleton on port 48322 — run one form or the other, never both.

`record.sh` attaches to whatever runtime is up and starts its own when there is none, so
this terminal is a convenience. It is worth having: the runtime takes tens of seconds to
come up and one of these outlives any number of takes.

**Connect the headset over Wi-Fi.** The panel receives nothing until the headset is
streaming, and sits at *waiting for a frame with valid joints* until it is. Put the
headset on the same subnet as this host, then

```bash
$PY -m isaacteleop.cloudxr.webclient --print-only
```

That prints two things: the streaming target `https://<this-host>:48322/` and the client
URL with that address and port already filled in.

**Open the streaming target in the headset's browser first and accept the self-signed
certificate.** Until you have, the client page loads normally and CONNECT fails with
nothing in either log. Then open the client URL and press CONNECT.

Dropping `--print-only` types the client URL into the headset for you over USB `adb`,
which saves the typing and needs USB debugging authorised on the headset. It changes
nothing about how the session streams — the cable is for `adb`, not for the video. Re-run
either form whenever the headset browser gets closed or navigated away; it does not
disturb a running take.

Anything `record.sh` does not itself understand is passed through to the panel, so the
runtime flags work from there too — `--cloudxr-install-dir` (default `~/.cloudxr`) and
`--cloudxr-device-profile` (default `Quest3`) among them. Run
`capture_panel.py --help` for the full list.

Two references worth having open the first time:

- [`docs/source/references/cloudxr.rst`](../../docs/source/references/cloudxr.rst) —
  device profiles, foreground vs detached service, out-of-band and USB-only setups.
- [`docs/source/device/body_tracking.rst`](../../docs/source/device/body_tracking.rst)
  — which PICO Motion Tracker configurations are supported (5, 3 or 2 trackers), how to
  calibrate them, and what body tracking needs from the headset. **Read this before your
  first take**: without body tracking the recording contains no usable joints and only
  the container checks can run.

## Recording from a device you integrated yourself

The joints come from the headset's own `body.pico-xr` backend unless you say otherwise. A
suit, gloves or any other full-body device arrives instead as a **vendor**, a backend id
the session resolves when it is constructed, fed by a **plugin** process the session
launches. Both are `capture_panel.py` flags, so `record.sh` passes them through:

```bash
acceptance/full_body/capture/record.sh mysuit \
    --plugin my_body_plugin \
    --vendor body.my-vendor \
    --vendor-param collection_id=my_body
```

- `--plugin NAME` names a directory under `plugins/` or `install/plugins/`, so the plugin
  must be installed (`cmake --install build`) before the take. It is launched as
  required: a plugin that fails to load stops the take instead of recording a file with
  no body in it.
- `--vendor ID` selects the backend from the live factory's vendor registry. An unknown
  id is rejected at session construction, not at the first frame.
- `--vendor-param KEY=VALUE` is repeatable and free-form. `collection_id` has to match
  what the plugin publishes under; a mismatch records an empty take and looks exactly
  like a device that never connected.
- CloudXR still runs, because the head pose and the controllers come through it. A suit
  has no trigger, so the performer opens every window with the space bar.

The device name is the first argument and only decides where the take lands, so
`mysuit` above gives `~/isaacteleop-captures/mysuit_<date>_<time>/`. The checker judges
the result identically either way: it reads the recorded `full_body` channel and never
asks what produced it.

**No full-body plugin ships in this tree and this path is not yet exercised end to end.**
`install/plugins/` holds controller, pedal and leader-arm plugins, and the vendor registry
has the one entry. Writing the backend and its plugin comes first —
[`docs/source/device/trackers.rst`](../../docs/source/device/trackers.rst) under *Vendor
Selection* is the reference. Tell us before planning a take around this rather than
working from `--help`.

## Record

```bash
acceptance/full_body/capture/record.sh pico4u
```

The argument names the device and only decides where the files land; `pico4u` is the
default. On the first run CloudXR asks you to accept its EULA — pass `--accept-eula`
after the device name to skip the prompt.

Open the panel at <http://localhost:8081>. It binds every interface, so the headset's
own browser can reach it at `http://<your-host>:8081` as well.

The cues sit in a column down the right edge and the skeleton gets the room to the left
of it. Drag the column's inner edge to change the split. If the text is too small to
read from where the performer stands, zoom the browser in with `Ctrl+=` — it scales the
text and the column together, and the browser remembers the setting for that address.

The panel idles. Nothing is open against the device and no file exists yet. Press
**Start recording** when the performer is standing ready — that is when the recording is
created. The script itself begins at the first frame with valid joints, which is normally
the next moment but is not the same one.

If ten seconds go by with no valid joint, a red box appears at the bottom left of the
skeleton area listing what to check. It stops nothing: the take is still running, the
file is still being written, and the script still starts at the first valid frame
whenever it arrives. The box clears itself when it does.

Then, for each of the ten steps:

1. The cue is spoken and shown on the panel — *"T pose. Hold."*
2. The performer gets into the pose. Take as long as you need; nothing is running out.
3. **Press the controller trigger, or the space bar.**
4. A beep. Hold the pose while the countdown on the panel runs down.
5. A tick. That pose is recorded, and the next cue follows.

Two things to know before your first take:

- **The space bar is a key in the _browser_, not in the terminal.** It works in whichever
  browser has the panel open and focused — the headset's or the one on your desk. With
  two people, the one at the screen does the pressing.
- **Pressing at any other moment does nothing, deliberately, and the panel will not
  react.** It is not broken and the press is not queued. Press once, when the performer
  is in the pose.

If the performer already knows the pose, they can press during the spoken cue to cut it
short and go straight to waiting.

After the tenth pose the recording closes, *"Done. You can stop now."* plays, and the
panel reports what the labels came out as. The first few rows are about the file itself
— how many records it holds, whether every one carries a timestamp, whether all ten
windows resolved. The rows after those are named after the steps, and each one
re-derives that pose from the recording, so a `BAD` there means the window does not hold
the pose it claims. How many are `BAD` is what says whose fault it is: one row against
otherwise good ones is that step, pressed at the wrong moment or performed wrongly. Most
of them at once, with degenerate numbers like `pelvis drops 0 cm`, is the joint stream,
and recording again reproduces it exactly.

The process keeps serving the report; Ctrl+C when you have read it.

## What you get

One directory per take, under `~/isaacteleop-captures/`, named for the device and the
moment you pressed the button:

```text
pico4u_2026-03-04_101530/pico4u_2026-03-04_101530-g4.mcap          the recording
                        /pico4u_2026-03-04_101530-g4.labels.json   the motion-step windows
                        /pico4u_2026-03-04_101530-g4.json          what produced it
                        /pico4u_2026-03-04_101530-g4.log           the panel's output
```

Nothing is ever overwritten. Run `record.sh` again for another take and both are kept.

All four files belong together, which is why they share a directory and why they repeat
its name: sending a take is sending the directory, and the recording still says what it
is once it is out of there. The labels **cannot** be regenerated from the recording
afterwards, so keep them beside it.

There is deliberately no `latest` shortcut to the newest take. The checker finds the
labels at `<recording>.labels.json` **as you spelled the recording**, so any alias to one
finds no labels beside itself: measured on a real take, the true path reports `retake`
while a symlink to it reports `pass` with thirteen G4 checks silently unanswered. Give
the full path.

Then run the checks — [`checker/README.md`](checker/README.md) covers reading the
verdict and packaging a take to send.

## If something goes wrong

| What you see | What to do |
|---|---|
| `Command 'python' not found` | Use the interpreter the setup built, `acceptance/full_body/capture/.venv/bin/python`. Ubuntu has `python3` and no `python`, and neither has `isaacteleop`. |
| `missing …/.venv; run …/setup_env.sh` | Run the two setup scripts above. |
| `no isaacteleop wheel in …/wheels; build the repo first` | Build the project, then re-run `capture/setup_env.sh`. |
| `run …/checker/setup_env.sh first` | You ran the two setup scripts in the wrong order. |
| **the session did not open**, on the panel | CloudXR could not start or the headset is not connected. The message names the reason. Nothing was recorded; fix it and run `record.sh` again. |
| The client page loads but CONNECT does nothing | The headset has not accepted the runtime's self-signed certificate. Open `https://<this-host>:48322/` in the headset browser, click through the warning, then go back to the client. Failing that: same subnet, and the host firewall allows 48322. |
| The service prints `running` but a second one will not start | The runtime is a host singleton on 48322. One is already up — `service status` names it, `service stop` ends a detached one, Ctrl+C a foreground one. |
| **body_tracking is off**, in the cue column | On PICO this is the browser, not the hardware or a licence: use the headset's own browser, which grants WebXR body tracking on a consumer 4 Ultra. |
| **No body data after 10 s**, in red under the skeleton | The same thing as the row above, once it has lasted ten seconds, with the causes spelled out. Two red things, one problem. Nothing has been lost: no joint has been valid since you pressed **Start recording**, so the script has not begun. Fix what the box names and the script starts on its own — same take, same file, nothing to redo. |
| No sound, or a `FileNotFoundError` naming `aplay` | `aplay` is missing. Install `alsa-utils` and record again. |
| The panel is not at 8081 | Something else held that port, so it moved to the next free one. Use the `http://localhost:…` line the run prints, which is always the real one. |
| The headset's browser cannot load the panel | The port is not reachable from the headset. Check the host firewall; the panel itself listens on every interface. |
| One `BAD` row in the label report, the rest `ok` | That pose was pressed at the wrong moment or performed wrongly. Record another take. |
| Most rows `BAD`, with degenerate numbers (`pelvis drops 0 cm`, both hands at one height) | The joint stream is frozen: every window holds the same still pose, and one row can still read `ok` by accident. Why it freezes is not yet known, so report it — re-performing the script changes nothing. The checker confirms it with `continuity.max_joint_velocity` at `peak 0.0 m/s`. |

## Do not edit the script

The ten steps, their spoken cues and their hold durations are part of the acceptance
specification, and the checker looks its measurements up by step name. Changing any of
them under `capture/` silently changes what the verdict means.

If a take stops with

```text
the wording of cue 'squat_x2' changed, so squat_x2.wav no longer says it
```

then the capture side has drifted out of sync with its own audio. That is ours to fix —
report it rather than working around it.
