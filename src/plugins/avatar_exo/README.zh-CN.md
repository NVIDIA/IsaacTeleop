<!--
SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
SPDX-License-Identifier: Apache-2.0
-->

# Avatar 外骨骼手套插件（`avatar_exo`）

`avatar_exo` 用于把 Avatar 外骨骼手套的数据接入 Isaac Teleop。插件内置 Avatar SDK（`sdk/`），运行时可以按需发布三类数据：

| 数据集 | Avatar SDK 数据源 | 进入 Isaac Teleop 的方式 | 主机侧消费者 |
|--------|-------------------|--------------------------|--------------|
| `raw` | `RAW` 原始关节角 | `JointStateOutput` + `SchemaPusher` | `JointStateSource` |
| `robot` | `ROBOT` 重定向后的机器人关节角 | `JointStateOutput` + `SchemaPusher` | `JointStateSource` |
| `human` | `HUMAN` 手部骨架关键点 | 26 个 OpenXR 手关节 + `HandInjector` | `HandsSource` / 手部 tracker |

## 工作方式

插件进程拥有一个 `core::OpenXRSession` 和 Avatar SDK 单例。启动后，工作线程会按 `--rate-hz` 周期轮询左右手套；Avatar SDK 初始化和手套发现都在工作线程里重试，因此手套未插入或 backend 晚启动时不会让宿主 `TeleopSession` 崩溃。

`raw` 和 `robot` 走通用关节空间链路：每个 `(dataset, side)` 都会发布到一个 collection id，例如 `avatar_robot_left`。关节名固定为 `j0..jN-1`，server 侧的 `JointStateSource` 也声明同一组名字，因此不需要把 Avatar 配置文件传给主机。`--config` 只用于 Avatar SDK 初始化和资源路径解析，不改变 `JointStateOutput` 里的关节名。

`human` 走 OpenXR 手部链路：插件把 `HandSkeleton.landmark` 映射为 26 个 `XrHandJointEXT`，再通过 `plugin_utils::HandInjector` 注入运行时。映射表位于 `avatar_exo_plugin.cpp` 的 `kHumanLandmarkForJoint`，默认匹配随插件提供的 HA2_4 `human_joint_names` 布局。

## 构建

在 IsaacTeleop 根目录下构建：

```bash
cd external_dependencies/IsaacTeleop
cmake -B build \
    -DISAAC_TELEOP_PYTHON_VERSION=3.10 \
    -DBUILD_EXAMPLES=OFF -DBUILD_TESTING=OFF -DENABLE_CLANG_FORMAT_CHECK=OFF
cmake --build build --parallel
```

构建完成后，二进制、`plugin.yaml` 和 `sdk/` 会被复制到 `build/src/plugins/avatar_exo/`。如果需要安装布局，可继续执行：

```bash
cmake --install build
```

安装后插件位于 `install/plugins/avatar_exo/`，SDK 动态库也会安装到 IsaacTeleop 的 lib 目录，供安装树 rpath 解析。

## 单独运行

```bash
# 左右手、三类数据全部启用，使用插件旁边的 ./sdk/sdk_config.json：
./build/src/plugins/avatar_exo/avatar_exo_plugin \
    --datasets=raw,robot,human --sides=both

# 只启用右手 RAW：
./avatar_exo_plugin --datasets=raw --sides=right

# standalone 调试时使用显式 Avatar SDK 配置：
./avatar_exo_plugin \
    --datasets=robot,human --sides=left,right \
    --config=/absolute/path/to/sdk_config.json
```

常用参数：

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `--datasets=` | 无 | 逗号分隔的 `raw,robot,human`，至少启用一个。 |
| `--sides=` | `both` | `both`，或逗号分隔的 `left,right`。 |
| `--collection-prefix=` | `avatar` | RAW/ROBOT collection id 前缀。 |
| `--config=` | `./sdk/sdk_config.json` | standalone 调试时可覆盖 Avatar SDK 初始化 JSON；server 不传这个参数。 |
| `--rate-hz=` | `90` | 工作线程轮询/发布频率。 |
| `--plugin-root-id=` | 无 | `PluginManager` 注入，插件会忽略。 |

## 与 `isaac_teleop_server.py` 集成

`groot.control.teleop.device.isaac_teleop_server` 会通过 `PluginManager` 启动该插件，并默认启用 `robot` 和 `human`：

```bash
python -m groot.control.teleop.device.isaac_teleop_server
```

server 不接收 Avatar 配置文件，也不会把 `--config` 传给插件。`robot` 链路固定使用 `j0..j21` 的位置式关节名；这些值的顺序对应 SDK 配置中的 `robot_joint_names`，需要查手指/关节含义时可把该列表当作离线索引表。

`human` 数据会出现在快照中的 `poses.left_hand` / `poses.right_hand` 和 `hand_fingertips`。`robot` 数据会出现在顶层键 `avatar_robot_left` / `avatar_robot_right`，值为关节位置数组；在手套未连接或尚未收到数据时为 `None`。

## 排障

- 插件只把 OpenXR session 创建视为硬依赖；Avatar SDK 初始化失败或暂时找不到手套时会持续重试。看到 `AvatarSDK.initialize failed; retrying` 时，检查 Avatar backend、网络/串口和 `--config`。
- `human` 需要运行时支持 push devices。若日志中出现 `xrCreatePushDeviceNV: Push devices not supported by this system`，在 `~/cloudxr.env` 中设置 `NV_CXR_ENABLE_PUSH_DEVICES=1`，然后重启 CloudXR runtime 和 server。
- RAW/ROBOT 依赖 tensor data，通常需要 `NV_CXR_ENABLE_TENSOR_DATA=1`。
- `robot` 数据需要 SDK 配置中 `retarget_update_rate_hz >= 1`。如果没有 robot stream-start 日志，优先检查 `sdk_config.json` 是否被正确读取，以及 `hand_fk` / Wave SDK 路径是否能解析。
- 如果 `avatar_robot_<side>` 一直是 `None`，通常表示插件还没有发布 robot 样本：检查手套连接、Avatar backend、`retarget_update_rate_hz` 和 CloudXR tensor data 开关。若是全零但 stream-start 日志已出现，则优先检查 Avatar SDK retarget 输出本身。

## 维护注意事项

- `kHumanLandmarkForJoint` 是手套布局相关的唯一映射表；换手套或换 `human_joint_names` 顺序时先检查这里。
- server 集成路径固定使用 `j0..j21` 命名；不要在默认路径下改成语义名，除非同步更新 server、插件和下游消费者。
- 每个输出（RAW、ROBOT、HUMAN）独立创建。HUMAN 注入失败时，不应阻塞 RAW/ROBOT 数据流。
