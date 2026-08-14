.. SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
.. SPDX-License-Identifier: Apache-2.0

Ecosystem
=========

The Isaac Teleop ecosystem brings together the NVIDIA platforms it is built into and the input
devices, robot embodiments, and data services that work seamlessly with the unified teleoperation
stack. Browse every entry and follow the link straight to its landing page, integration guide, or
acquisition channel.

.. eco-block:: eco-scope

   .. eco-block:: eco-scope-item

      **Input devices**

      Headsets, controllers, gloves, pedals, and master manipulators.

   .. eco-block:: eco-scope-item

      **Robot and simulation integrations**

      Embodiments and assets for control and retargeting.

   .. eco-block:: eco-scope-item

      **Data workflows**

      Tools and services for recording, processing, and managing teleoperation data.

.. rst-class:: eco-eyebrow

Built and used inside NVIDIA

.. Explicit targets on every section below: the count pill is part of the heading text,
   so without them the slug carries the count and #partners becomes #partners-15,
   changing every time a card is added or removed.

.. _nvidia-platforms:

.. rst-class:: eco-section

NVIDIA Platforms :partner-count:`platform`
------------------------------------------

Stacks Isaac Teleop is developed against, and NVIDIA teams collecting data with it.

.. partner-grid::
   :section: platform

.. rst-class:: eco-eyebrow

Active in the ecosystem

.. _partners:

.. rst-class:: eco-section

Partners :partner-count:`active`
--------------------------------

Production-ready integrations that partners actively maintain and support across releases.

.. partner-grid::
   :section: active

.. rst-class:: eco-eyebrow

Joint plan in place

.. _upcoming-partners:

.. rst-class:: eco-section

Upcoming Partners :partner-count:`upcoming`
-------------------------------------------

A joint development plan is in place with NVIDIA and integration work is scoped or underway.

.. partner-grid::
   :section: upcoming

Become a Partner
----------------

.. eco-block:: eco-cta

   .. eco-block:: eco-cta-title

      Bring your device or service to Isaac Teleop

   If you build input devices, robot embodiments, or data services, let's plan a joint
   integration together. Devices connect through a plugin process, so your SDK stays in your
   own repository under your own license.

   .. eco-block:: eco-cta-actions

      `Become a Partner <https://forms.gle/Fo5nRUHZivGN1itg9>`_

      .. Hidden until the dedicated integration page exists. Uncomment and retarget
         the doc reference then.
         :doc:`Read the integration guide </device/add_device>`

   .. rst-class:: eco-cta-steps

   #. **Joint plan** — agree on scope, devices, and timeline.
   #. **Implementation** — build the plugin and open a pull request.
   #. **Maintenance** — keep the integration green across releases.

.. rst-class:: eco-eyebrow

One interface, any device

.. _supported-input-devices:

.. rst-class:: eco-section

Supported Input Devices :device-count:`all`
-------------------------------------------

A standardized device interface removes custom integrations and their maintenance. Input
modes determine which retargeters and control schemes are available.
:doc:`Add a new device → </device/add_device>`

.. device-matrix::
