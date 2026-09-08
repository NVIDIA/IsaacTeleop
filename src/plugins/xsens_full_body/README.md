<!--
SPDX-FileCopyrightText: Copyright (c) 2026 Xsens Technologies B.V. All rights reserved.
SPDX-License-Identifier: Apache-2.0
-->

# xsens_full_body plugin

Receives Xsens MVN Studio's **Isaac Teleop** UDP stream and republishes it as an Isaac Teleop
tensor collection, readable through the `body.xsens` vendor.

```
MVN Studio  --UDP 9764 (XTLP)-->  xsens_full_body_plugin  -->  collection "xsens_full_body"
                                                                tensor "full_body_pose"
```

## Why it is this small

MVN Studio does the skeleton conversion itself: its network-streamer preset converts the
23-segment MVN skeleton to the vendor-neutral 24-joint `XR_BD_body_tracking` layout and emits a
`core::FullBodyPose` FlatBuffer — the same schema this repository defines. So the plugin needs no
vendor SDK, and **forwards the payload bytes verbatim**; re-serializing would risk silently
changing a pose and buys nothing.

## Running

```bash
source ~/.cloudxr/run/cloudxr.env          # in this shell and every consumer's
./xsens_full_body_plugin \
    --collection-id=xsens_full_body \
    --address=0.0.0.0 \
    --port=9764 \
    --max-flatbuffer-size=4096
```

Every flag shown is its default, so bare `./xsens_full_body_plugin` is the same invocation; the
defaults match MVN's "Isaac Teleop" preset. `--address` picks the interface to bind — the default
accepts the stream on any of them, and `--address=127.0.0.1` confines the pusher to loopback.

Then in MVN Studio: **Options → Network Streamer → preset "Isaac Teleop"**, tick the destination
row, and move in the suit or press **Play** on a recording.

Reader side:

```python
tracker = deviceio.FullBodyTracker()
vendor  = deviceio.VendorConfig([(tracker, deviceio.TrackerVendor("body.xsens", {
    "collection_id": "xsens_full_body", "max_flatbuffer_size": "4096"}))])
# NB: pass `vendor` to get_required_extensions() as well, or the pushed-tensor extensions are
# never requested and the session silently never sees the collection.
```

## Things that will bite

- **Order matters.** The pusher creates the collection, so a consumer started first reports "no
  collection found" forever.
- **A `collection_id` mismatch fails silently and forever** — the two sides rendezvous on that
  string. A `max_flatbuffer_size` mismatch, by contrast, throws loudly and names the right value.
  So when a reader sees nothing, suspect the collection id first.
- **`--address` has the same silent failure signature.** Bind to one interface and point MVN at a
  *different* local address, and the datagrams are simply never delivered — no error on either
  side, identical to a collection-id mismatch. A bad address is at least rejected at startup: only
  a literal IPv4 is accepted, hostnames included, because an unresolvable name would otherwise
  surface much later as an opaque `EADDRNOTAVAIL`.
- **22 of 24 joints valid is correct.** MVN has no finger tracking, so `LEFT_HAND` (22) and
  `RIGHT_HAND` (23) carry a copy of the wrist pose flagged invalid, and `all_joint_poses_tracked`
  is structurally always false. Consult the per-joint flags.
- **A sequence gap is not proof of packet loss, and the stats line reports two figures for it.**
  `gapEvents` is how many times continuity broke; `seqSkipped` is how many sequence numbers went
  missing in total. One 500-frame dropout and 500 single-frame losses are the same `seqSkipped`
  and very different faults, which is why neither number is reported alone.

  Neither is a link-quality figure on its own. A number goes missing when MVN declines to build
  that frame (`seq` is sent-only: invalid pose, fewer than 23 segments, any non-finite
  component), when a datagram is genuinely lost in transit, and when the pusher itself rejects
  one — the verifier runs before the sequence machine, so a payload we refuse leaves a hole
  exactly like a dropped datagram. A long session outage also produces them, because the pusher
  stops draining the socket while it retries. A step back to 0 is a new MVN session, not a gap.
- **Timestamps are two different clocks.** The header's `sample_time_ns` is on MVN's send-host
  clock and is deliberately *not* published as the local common clock; the plugin stamps that
  itself at publish time and forwards MVN's device clock verbatim alongside it.
- **Nothing is ever dropped on a timestamp.** Both timestamp rules are diagnostics: a sample time
  that is not a whole millisecond (`nonWholeMs`) did not come from MVN's solver, and one that
  moves backwards (`rewinds`) is a scrub or a recording restart. Neither rejects the frame — the
  pose has already passed the structural verifier, and nothing downstream decodes the sample
  time. Dropping on either would discard good poses for a metadata fault: rejecting rewinds once
  cost 1315 frames of a looped playback, and rejecting sub-millisecond times would stop the robot
  the moment MVN's clock granularity changed. `seq` is the authority on frame identity, not the
  clock.

## Outages it survives on its own

Both of the plugin's dependencies can disappear underneath it and come back. Neither is fatal, and
neither needs an operator: `update()` recovers on a bounded backoff and only throws once a retry
budget is exhausted — at which point the process exits 1 *after* printing its counters, because
those are usually the only record of what led up to it.

| What goes away | Retry budget | Counter |
|-|-|-|
| The UDP socket fails hard (`recv` errors with anything other than `EAGAIN` / `EWOULDBLOCK` / `EINTR`) | 5 re-binds of the same port over ~2.3 s | `socketRecoveries`, `socketRecoveryFailures` |
| The CloudXR runtime is restarted, so `push_buffer` throws | 8 session re-establishes over ~23.5 s | `pushFailures`, `sessionRecoveries` |

Two details worth knowing:

- **A restarted runtime needs a full re-create, not a re-connect.** Once its IPC pipe breaks, the
  pusher's collection handle is dead, so recovery tears down the pusher *and* the session before
  rebuilding both. A dead runtime arrives as `XR_ERROR_RUNTIME_FAILURE`, not as anything
  session-shaped.
- **Stream state deliberately survives an outage.** Neither recovery path resets `seq` tracking:
  the outage reappears as a sequence gap or a session reset, and both are already handled. Expect
  `seqSkipped` to climb across a long one — the socket is not being drained while the pusher
  retries, so the kernel discards what arrives.

`SIGINT`/`SIGTERM` are observed *inside* the backoffs, so Ctrl-C during a 23-second outage stops
the pusher promptly rather than waiting the budget out.

**Testing the socket path.** A real hard `recv` error needs the interface to fail underneath you,
so `XSENS_TELEOP_INJECT_RECV_ERRORS=<n>[:<errno>]` forces the next *n* receives to fail
(`ENOTCONN` by default). Unset in production; it announces itself loudly when set.

```bash
# three forced hard errors: expect socketRecoveries=3 and an unbroken stream
XSENS_TELEOP_INJECT_RECV_ERRORS=3 ./xsens_full_body_plugin --address=127.0.0.1
```

The session path needs no hook: `kill` the CloudXR runtime while streaming, and restart it inside
~23.5 s to watch it recover, or leave it down to watch it give up.

Log lines are throttled per category — first occurrence and every hundredth, tagged `(xN)` — so a
lossy link or an operator scrubbing a recording cannot flood the console from inside the receive
loop. Stream diagnostics go to stdout; problems (bad sender, broken socket, dead runtime) go to
stderr.

## Tests

`frame_decision.{hpp,cpp}` holds everything the pusher *decides* about a datagram — framing, the
size check, the structural verifier, the sequence state machine and the timestamp rules — with
none of the I/O it decides it for. It is split out so it can be tested: the plugin itself owns a
socket and an OpenXR session and cannot be constructed without a running CloudXR runtime, so this
logic was previously reachable only through a live end-to-end run.

`plugin_options.{hpp,cpp}` is split out for the same reason and holds everything the pusher
decides about a *command line*: which form was used, what each flag means, and what is rejected
before anything binds.

```bash
# from the IsaacTeleop checkout, once configured with -DBUILD_TESTING=ON (see apply.sh)
ctest --test-dir build-py312 -R 'xsens_' --output-on-failure

# or, with no build tree at all -- neither unit needs one
g++ -std=c++20 -I. -I<generated-schema-dir> -I<flatbuffers-include> \
    tests/test_frame_decision.cpp frame_decision.cpp -lflatbuffers -o /tmp/t && /tmp/t
g++ -std=c++20 -I. tests/test_plugin_options.cpp plugin_options.cpp -o /tmp/o && /tmp/o
```

114 and 120 assertions respectively, no runtime, no socket, no suit, milliseconds to run. The
frame-decision suite is mutation-checked: inverting the stale comparison, the rewind comparison,
the whole-millisecond flag, the oversize check or the verifier, dropping the timeline clear on
session reset, putting the duplicate-`seq`-0 defect back, or collapsing the skipped-sequence
count back to a flag, each make it fail.

Three frame-decision behaviours it pins that are easy to get wrong by accident:

- **The verifier runs before the sequence machine, so a payload it rejects never consumes its
  sequence number** and the next frame reads as a gap. That is deliberate: an unverified payload
  must not be able to advance stream state at all. Everything that gets past the verifier does
  consume its number, delivered or not.
- **A session reset clears the timeline**, so the new session's first timestamp is not reported
  as a rewind.
- **A repeat of `seq` 0 is a duplicate, not a new session.** Only a step back to 0 from a
  *non-zero* seq is a session boundary. The decider therefore holds the last seq it saw rather
  than the next one it expects: the two differ by one, and writing the reset test against the
  expected value is what produced the defect this test now guards (a duplicate at seq 0 counted
  as a reset, cleared the timeline, and got pushed to the robot).

## Wire format

One frame per datagram: a 36-byte little-endian header, then the payload. See `teleop_wire.hpp`;
the authority is `bsn_stack/mvn/mvn_studio/src/picofullbody_core/teleop_wire.h`.

| offset | size | field |
|---|---|---|
| 0 | 4 | magic `"XTLP"` |
| 4 | 2 | version = 1 |
| 6 | 2 | reserved — v1 receivers MUST ignore |
| 8 | 8 | `seq` (uint64) |
| 16 | 8 | `sample_time_ns` (int64, MVN send-host clock) |
| 24 | 8 | `raw_device_time_ns` (int64, MVN device clock) |
| 32 | 4 | `payload_len` (uint32) |

A live MVN pose is 820 bytes: 36 B header + 784 B payload (16 B table/vtable + 24 × 32 B joint
structs). Meters, **Y-up** (OpenXR), quaternions **xyzw**, absolute global poses.
