.. SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
.. SPDX-License-Identifier: Apache-2.0

Retargeter: Manus to Sharpa
===========================

``SharpaHandRetargeter`` maps live hand-tracking poses from a `Manus glove
<https://www.manus-meta.com/>`_ (or any other source feeding the OpenXR
hand-tracking layer) onto Sharpa hand joint angles, frame by frame, via
optimization-based inverse kinematics. ``SharpaBiManualRetargeter`` is a
thin combiner that interleaves left and right outputs into a single
target-ordered vector for downstream control.

At a glance
-----------

.. list-table::
   :header-rows: 1
   :widths: 22 78

   * - Stage
     - What happens
   * - Input
     - 26-joint OpenXR ``HandInput`` for the configured side (xyzw quats),
       sourced from a Manus glove plugin or any other OpenXR hand-tracking
       provider.
   * - Repack
     - Drop OpenXR palm + non-thumb metacarpals to land on the canonical
       MANO 21-joint layout, and convert quaternions to wxyz.
   * - IK
     - ``robotic_grounding.retarget.hand_kinematics.SharpaHandKinematics``
       runs Pink IK on a Pinocchio model loaded from the Sharpa MJCF, with
       a FreeFlyer root that re-anchors the wrist each frame.
   * - Warm-start
     - Previous-frame qpos is kept and reused (with the wrist re-pinned to
       the new tracker reading) to keep the IK locally smooth. A frame
       with any invalid input joint zeros the output and resets the
       warm-start.
   * - Output
     - Sharpa finger DOFs (everything Pinocchio reports past the
       FreeFlyer), optionally reordered by ``hand_joint_names``.

The retargeter intentionally contains no IK math itself: joint orderings,
frame mappings, rotation corrections, and Pink/Pinocchio configuration all
live in ``robotic_grounding`` (V2D). This module is the OpenXR-shaped
adapter on top of it.

.. seealso::

   :doc:`/device/manus` -- installing the Manus plugin so its tracking
   shows up on the OpenXR hand layer that this retargeter consumes.

   :doc:`index` -- the broader retargeting interface and pipeline-builder
   pattern.

Why the ``[grounding]`` extra exists
------------------------------------

The Sharpa kinematics model, MJCFs, meshes, and the IK setup that this
retargeter calls all live in the ``robotic_grounding`` package (part of
V2D). V2D is on track to be fully open sourced; until then its source
isn't public, so the wheel has two build modes:

* **Default** — wheel ships without ``robotic_grounding``. Sharpa
  retargeter imports skip cleanly, so forks and OSS contributors can
  build and use the rest of Teleop unaffected.
* **With** ``-DBUNDLE_ROBOTIC_GROUNDING=TRUE`` — the build pulls
  ``robotic_grounding`` from the pinned SHA in ``deps/v2d/version.txt``
  and bundles it into the wheel. Installing ``isaacteleop[grounding]``
  then resolves all imports, and the Sharpa MJCFs ship with the wheel.

.. note::

   ``-DBUNDLE_ROBOTIC_GROUNDING=TRUE`` is a temporary bridge. Once V2D is
   fully open sourced, ``robotic_grounding`` will be a normal public
   dependency of the ``[grounding]`` extra and the bundling flag (along
   with ``scripts/setup_v2d_src.sh`` and the ``V2D_RETARGETER_TOKEN``
   gating in CI) will go away.

The next two sections cover that opt-in build, how to use the retargeter
once the extra is in place, and how to verify the install.

Build the ``[grounding]`` extra
-------------------------------

Prerequisites:

* `gh CLI <https://cli.github.com/>`_ installed and ``gh auth login``\ 'd
  with read access to ``jiwenc-nv/v2d``.
* A configured Teleop build tree.

.. code-block:: console

   $ scripts/setup_v2d_src.sh
   $ cmake -B build -DBUNDLE_ROBOTIC_GROUNDING=TRUE <other flags...>
   $ cmake --build build --target python_wheel
   $ uv pip install -e .[grounding]

The first command populates ``deps/v2d/src/robotic_grounding/`` from the
SHA pinned in ``deps/v2d/version.txt``. The CMake flag tells the wheel
build to bundle that subtree alongside ``isaacteleop``.

If the wheel was built without ``-DBUNDLE_ROBOTIC_GROUNDING=TRUE``, the
import raises ``ModuleNotFoundError`` with a pointer back to
``scripts/setup_v2d_src.sh``.

Use it from Python
------------------

.. code-block:: python

   from isaacteleop.retargeters import (
       SharpaHandRetargeter,
       SharpaHandRetargeterConfig,
   )

The Sharpa MJCFs and meshes ship inside the bundled ``robotic_grounding``
package -- resolve them with ``importlib.resources``:

.. code-block:: python

   from importlib.resources import files

   xml_dir = files("robotic_grounding") / "assets" / "xmls" / "sharpawave"
   right_mjcf = str(xml_dir / "right_sharpawave_nomesh.xml")  # mesh-free, fast
   # or "right_sharpawave.xml" if you also have the STL meshes

   cfg = SharpaHandRetargeterConfig(hand_side="right", robot_asset_path=right_mjcf)
   retargeter = SharpaHandRetargeter(cfg, name="sharpa_right")

Key ``SharpaHandRetargeterConfig`` fields:

* ``robot_asset_path`` — the Sharpa MJCF path (``..._nomesh.xml`` is the
  mesh-free variant used in tests and on machines without the STLs).
* ``hand_side`` — ``"left"`` or ``"right"``.
* ``hand_joint_names`` — optional output ordering override; defaults to
  whatever finger joints Pinocchio discovers in the MJCF, in model order.
* ``source_to_robot_scale`` — MANO-to-robot length scale.
* ``solver`` / ``max_iter`` / ``frequency`` /
  ``frame_tasks_converged_threshold`` — Pink IK knobs forwarded to
  ``SharpaHandKinematics``.

For bimanual control, instantiate two ``SharpaHandRetargeter``\ s and
wrap them with ``SharpaBiManualRetargeter`` so a single output vector is
produced in your target joint order.

Run the example
---------------

The repo ships a bimanual demo at
``examples/retargeting/python/sharpa_hand_retargeter_demo.py``:

.. code-block:: console

   # Synthetic curl animation (no headset, no GUI required):
   $ python examples/retargeting/python/sharpa_hand_retargeter_demo.py --synthetic

   # Live bimanual from a connected Quest headset:
   $ python examples/retargeting/python/sharpa_hand_retargeter_demo.py

   # Custom MJCFs (e.g. the mesh-bearing variants):
   $ python examples/retargeting/python/sharpa_hand_retargeter_demo.py \
       --left-mjcf  /path/to/left_sharpawave.xml \
       --right-mjcf /path/to/right_sharpawave.xml

The synthetic mode is the smoke test: if it animates a curl trajectory
and prints non-zero finger qpos each frame, the install is good.

Validate
--------

Two checks; either by itself is sufficient.

**End-to-end pytest** -- exercises the full Pinocchio + Pink IK pipeline
through the Teleop wrapper (init, warm-start persistence, open vs. curled
hand, absent-hand zeros, etc.):

.. code-block:: console

   $ ctest --test-dir build -R retargeting_test_sharpa_hand_retargeter --output-on-failure
   ...
   100% tests passed, 0 tests failed out of 1

The ``Test command`` line printed by ``ctest -V`` should include
``--extra grounding``. If it doesn't, the wheel build skipped bundling --
re-check that ``cmake -B build`` was invoked with
``-DBUNDLE_ROBOTIC_GROUNDING=TRUE`` after running ``setup_v2d_src.sh``.

**Full retargeting suite** -- regression coverage in case the wrapper
introduced a typing or import regression elsewhere:

.. code-block:: console

   $ ctest --test-dir build -R '^retargeting_' --output-on-failure
   ...
   100% tests passed, 0 tests failed out of 16

CI
--

The workflow at ``.github/workflows/build-ubuntu.yml`` runs the same flow
via the ``setup-v2d-src`` composite action, gated on the
``V2D_RETARGETER_TOKEN`` repo secret (a PAT scoped read-only to
``jiwenc-nv/v2d``). The action sets ``-DBUNDLE_ROBOTIC_GROUNDING`` from
its own ``bundled`` output; on forks without the secret the action no-ops
and the flag is ``false``.

Public artifact safety: a Release-only step strips ``robotic_grounding/``
out of every wheel before ``actions/upload-artifact`` runs, so V2D source
never reaches the public artifact channel.

Bumping the bundled ``robotic_grounding``
-----------------------------------------

Edit the SHA in ``deps/v2d/version.txt`` and rerun
``scripts/setup_v2d_src.sh``.
