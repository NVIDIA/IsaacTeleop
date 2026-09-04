<!--
SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
SPDX-License-Identifier: Apache-2.0
-->

# Vendored SIPL platform configs

`shw5g.json` is a **byte-identical copy** of

```
SG8A_AGON_G2Y_A1_AGX_ORIN_S56C_SHW5G_SHF3L_SIPL_JP7.2.1_L4TR39.2.1
  /query/sg8a_agth_g2a/shw5g.json
```

Copied so the plugin runs and its tests pass without the vendor package on
disk — `test_sipl_query` would otherwise skip, which in CI means it does not
exist.

Keep it byte-identical. When the vendor ships a new package, diff rather than
edit:

```bash
diff "$PKG/query/sg8a_agth_g2a/shw5g.json" src/plugins/sensing/configs/shw5g.json
```

This file describes board wiring — CSI ports, I2C buses, deserializer
addresses, power GPIOs, link modes. It is not tuning and it is not code, but it
must agree with the drivers in `/usr/lib/nvsipl_drv`, which the vendor package
installs. A mismatch shows up as a `SetPlatformConfig` failure, not as bad
pixels.

`--platform-config` overrides it; point that at the vendor package to test a
newer drop without touching the tree.
