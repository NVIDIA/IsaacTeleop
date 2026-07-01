#ifndef AVATAR_SDK_H
#define AVATAR_SDK_H

#include <array>
#include <cstdint>
#include <map>
#include <memory>
#include <optional>
#include <string>
#include <utility>
#include <vector>

#define AVATAR_SDK_VERSION "1.5.5"

/**
 * @file AvatarSDK.h
 * @brief Public API for the Avatar SDK.
 *
 * Naming convention: class names are PascalCase; all methods use snake_case.
 *
 * ## Overview
 *
 * AvatarSDK is the central manager. It handles transport connection and device
 * auto-discovery via heartbeat.
 *
 * To interact with a specific device, call get_device() to obtain an AvatarDevice
 * handle (DevicePtr). All per-device operations go through that handle.
 *
 * ## Transport
 *
 * Dual transport: a serial link carries high-rate joint streaming; a TCP command channel carries
 * requests, parameters, and discovery heartbeats. Pass JSON to initialize() with ``serial_port``,
 * ``ip``, and ``port`` (see example). Do **not** pass a ``backend`` key in product
 * configuration; when it is omitted, the implementation selects dual for normal hardware. An explicit ``backend`` field
 * is still parsed when present (e.g. unit tests or legacy callers).
 * Optional keys such as ``heartbeatIntervalMs``, ``requestTimeoutMs``, ``leftGloveIp``,
 * ``rightGloveIp`` follow ``TransportConfig`` parsing in the implementation.
 *
 * ## Usage
 * @code
 *   auto& mgr = avatar::AvatarSDK::get_instance();
 *   mgr.initialize(R"({"serial_port":"/dev/ttyACM0","ip":"192.168.10.40","port":59999})");
 *
 *   // Discovery
 *   for (auto& d : mgr.list_device_info())
 *       printf("%s %s\n", d.sn.c_str(), d.online ? "online" : "offline");
 *
 *   // Obtain a glove handle
 *   auto dev = mgr.get_device(avatar::DeviceType::GLOVE, avatar::DeviceSide::RIGHT);
 *   if (!dev) { return; }  // device not found
 *   dev->init("{}");
 *   dev->start();
 *
 *   // Read a frame. retarget_update_rate_hz controls ROBOT mode:
 *   // 0=disabled, 1..199=async cache, >=200=sync build in fetch_data(ROBOT).
 *   avatar::AvatarDataFrame frame;
 *   auto ec = dev->fetch_data(frame, avatar::DeviceDataCategory::RAW);
 *
 *   // Task plane (calibration, OTA, 3D force, …) — requires `"key"` in JSON
 *   auto [ec2, _] = dev->set_task(R"({"key":"zero_calib","joints":[0,1,2]})");
 *   auto [ec2b, prog_json] = dev->set_task(R"({"key":"get_upgrade_progress"})");
 *
 *   // Write / read a parameter
 *   dev->set_param(R"({"key":"coeff","value":{"k":[1,1],"b":[0,0]}})");
 *   auto [ec3, val] = dev->get_param(R"({"key":"coeff"})");
 *
 *   dev->stop();
 *   dev->destroy();
 *   mgr.destroy();
 * @endcode
 */

namespace avatar {

static constexpr uint32_t kDefaultRetargetUpdateRateHz = 0;

// ============================================================================
//  Wire-compatible data types (mirror avatar.proto, no protobuf dependency)
// ============================================================================

struct Stamp {
    int32_t sec     = 0;
    int32_t nanosec = 0;
};

struct Header {
    Stamp       stamp;
    std::string key;
    std::string frame_id;
    Stamp       sys_time;
    uint32_t    seq = 0;
};

struct Joint {
    std::vector<std::string> name;
    std::vector<float>       position;
    std::vector<float>       velocity;
    std::vector<float>       effort;
};

struct Point      { float x = 0, y = 0, z = 0; };
struct Quaternion { float w = 1, x = 0, y = 0, z = 0; };
struct Vector3    { float x = 0, y = 0, z = 0; };

struct Pose {
    Point      position;
    Quaternion orientation;
};

struct Hand {
    Header header;
    Joint  joint;
};

struct HandSkeleton {
    Header             header;
    std::vector<Pose>  landmark;
};

/// Wire-compatible frame container with oneof payload semantics.
struct AvatarDataFrame {
    enum PayloadCase { PAYLOAD_NOT_SET = 0, kRaw = 1, kRobot = 2, kSkeleton = 3 };

    Hand         raw;
    Hand         robot;
    HandSkeleton skeleton;

    PayloadCase payload_case() const { return payload_case_; }

    Hand*         mutable_raw()      { payload_case_ = kRaw;      return &raw; }
    Hand*         mutable_robot()    { payload_case_ = kRobot;    return &robot; }
    HandSkeleton* mutable_skeleton() { payload_case_ = kSkeleton; return &skeleton; }
    void          clear_payload()    { payload_case_ = PAYLOAD_NOT_SET; }

    bool        HasField(const std::string& name) const;
    std::string WhichOneof(const std::string& oneof_name) const;

    /// Serialize to protobuf binary (avatar.proto wire format).
    std::string SerializeAsString() const;
    /// Parse from protobuf binary (avatar.proto wire format).
    bool ParseFromString(const std::string& data);

private:
    PayloadCase payload_case_ = PAYLOAD_NOT_SET;
};

// Forward-declare so DevicePtr can reference AvatarDevice before its definition.
class AvatarDevice;
struct SerialDataSample;
struct WiredUdpJointSample;
struct WiredUdpDebugSample;
class SerialHand;
class IHandDevice;

// ============================================================================
//  Enums
// ============================================================================

enum class DeviceSide {
    LEFT  = 0,
    RIGHT = 1
};

enum class DeviceType {
    GLOVE   = 0,
    UNKNOWN = 0xFF
};

/** Lifecycle of the manager's USB serial discovery / high-rate data link (`serial_port` in `initialize()` JSON).
 *
 * This reflects whether that serial path was opened successfully — **not** TCP/PTC command channels,
 * Wi‑Fi, or per-glove online status (use `list_device_info()` for discovery rows).
 */
enum class UsbConnectionState {
    DISCONNECTED = 0,
    CONNECTING   = 1,
    CONNECTED    = 2,
    RECONNECTING = 3,
    ERROR        = 4
};

/// General error code for all SDK operations.
/// If the value is not SUCCESS, the operation failed.
enum class ErrorCode : int {
    SUCCESS = 0x00,

    // ---- Input / parameter ----
    INVALID_INPUT_PARAMETER   = 0x01,  ///< Invalid or missing required parameter
    OPERATION_NOT_ALLOWED     = 0x0D,  ///< Operation not permitted in current state (e.g. start() before init())

    // ---- Connection / transport ----
    CONNECTION_FAILED  = 0x02,  ///< SDK failed to connect (e.g. to transport or device)
    TCP_SEND_FAILED    = 0x10,  ///< TCP send failed
    TCP_RECV_FAILED    = 0x11,  ///< TCP receive failed
    INVALID_RESPONSE   = 0x12,  ///< Malformed or unexpected response from device
    DEVICE_NOT_FOUND   = 0x14,  ///< No device matching type/side/SN in discovery

    // ---- Device / data ----
    NO_VALID_DATA_RETURNED     = 0x03,  ///< No data (e.g. key not found, no frame yet)
    DEVICE_UNSUPPORTED_COMMAND = 0x05,  ///< Device does not support this command

    // ---- Protocol / packet ----
    INVALID_HEADER     = 0x09,  ///< Invalid protocol header
    INCOMPLETE_PAYLOAD = 0x0B,  ///< Incomplete or truncated payload (legacy; prefer INVALID_PAYLOAD)
    CRC_ERROR          = 0x0C,  ///< Checksum/CRC validation failed (legacy; prefer INVALID_PAYLOAD)
    INVALID_PAYLOAD    = 0x31,  ///< Invalid protocol payload/frame (too large, incomplete, CRC mismatch)

    // ---- Internal / device driver ----
    INNER_ERROR = 0x07,  ///< Firmware internal error (PTC 0x06 driver comm, 0x07 inner, 0x08 flash save)

    // ---- Task / OTA ----
    UPGRADE_IN_PROGRESS    = 0x20,  ///< OTA upgrade already in progress
    INVALID_FIRMWARE_FILE  = 0x30,  ///< Local OTA .bin invalid (path/size/CRC before upload)

    // ---- Unknown ----
    UNKNOWN_RSP_CODE = 0xFF,  ///< Unknown or unmapped response code from device
};

/// Hardware / firmware fault code reported via wired GET_DIAGNOSTICS / heartbeat or
/// wireless serial cmd=3 FAULT_CODE.
/// Used as keys in DeviceInfo::diagnostics and matches DeviceInfo::error_code.
/// Source: hand_master/App/diagnostics.h (feature/a2.4 d90ec9e). Encoding:
/// high byte = module, low byte = fault index.
enum class FaultCode : int {
    NORMAL        = 0x0000,  ///< No fault
    UNKNOWN_ERROR = 0x00FF,  ///< Unknown or unclassified fault

    // ---- 01 System ----
    SYS_LOAD_HIGH            = 0x0101,  ///< System running load high
    SYS_ZERO_ERROR           = 0x0181,  ///< Zero point error
    SYS_CALIB_ZERO_LOAD_FAIL = 0x0182,  ///< Calibration parameter load failed (zero)

    // ---- 02 Power ----
    PWR_BATTERY_LOW_WARN  = 0x0201,  ///< Battery low (e.g. below 30%)
    PWR_VOLTAGE_LOW       = 0x0240,  ///< Voltage below threshold
    PWR_BATTERY_CRITICAL  = 0x0241,  ///< Battery critically low (e.g. below 10%)
    PWR_OVER_CURRENT      = 0x0280,  ///< Current exceeds limit
    PWR_OVER_VOLTAGE      = 0x0281,  ///< Voltage exceeds limit

    // ---- 05 Motion / data acquisition ----
    MOTION_ANGLE_LIMIT_SOFT = 0x0501,  ///< Joint angle exceeds soft limit
    MOTION_VELOCITY_LIMIT   = 0x0502,  ///< Joint velocity limit exceeded
    MOTION_TORQUE_LIMIT     = 0x0503,  ///< Joint torque limit exceeded
    MOTION_RT_JITTER        = 0x0504,  ///< Control cycle jitter over limit
    MOTION_TASK_TIMEOUT     = 0x0505,  ///< Control task timeout
    MOTION_ANGLE_LIMIT_HARD = 0x0540,  ///< Joint angle exceeds hard limit

    // ---- 09 Encoder ----
    ENC_COMM_UNSTABLE     = 0x0901,  ///< Communication unstable (intermittent contact)
    ENC_OFFLINE           = 0x0940,  ///< Encoder communication error / offline
    ENC_MAG_FIELD_WEAK    = 0x0941,  ///< Weak magnetic field (magnet may be missing)
    ENC_VOLTAGE_ABNORMAL  = 0x0942,  ///< Encoder voltage abnormal
    ENC_DATA_ABNORMAL     = 0x0943,  ///< Encoder data abnormal (stuck / all zeros or ones)
    ENC_ANGLE_JUMP        = 0x0944,  ///< Encoder angle jump between frames

    // ---- 0A Vibrator ----
    VIB_COMM_UNSTABLE     = 0x0A01,  ///< Communication unstable (intermittent contact)
    VIB_DRIVER_OFFLINE    = 0x0A40,  ///< Driver communication error / offline
    VIB_MOTOR_CONNECTION  = 0x0A41,  ///< Vibration motor connection abnormal (open/short)
    VIB_DRIVER_OVERCURRENT = 0x0A42, ///< Driver overcurrent
    VIB_DRIVER_OVERTEMP   = 0x0A43,  ///< Driver overtemperature

    // ---- 0B Wireless ----
    WL_RSSI_WEAK            = 0x0B01,  ///< Received signal quality weak
    WL_GLOVE_NOT_CONNECTED  = 0x0B40,  ///< Glove not connected (dongle seen, glove unreachable)
    WL_RX_FPS_LOW_LEFT      = 0x0B41,  ///< Left receive FPS below threshold
    WL_RX_FPS_LOW_RIGHT     = 0x0B42,  ///< Right receive FPS below threshold
};

/// Data stream type selectable per device.
enum class DeviceDataCategery {
    RAW    = 0,  ///< raw joint angles / sensor packet
    ROBOT  = 1,  ///< cached robot-oriented joint frame (22 floats), produced by the device retarget worker.
    HUMAN  = 2   ///< human hand skeleton (forward-kinematics landmarks)
};

/// Corrected spelling for new code; ``DeviceDataCategery`` remains for ABI/API compatibility.
using DeviceDataCategory = DeviceDataCategery;

// ============================================================================
//  DeviceInfo – discovery / identity snapshot (replaces legacy DeviceHeartbeat)
// ============================================================================

/// Per-joint debug flags in wired UDP DebugPacket (firmware ``DEBUG_FLAG_*``).
namespace JointDebugFlags {
inline constexpr uint8_t FRAME_OK     = 1u << 0;
inline constexpr uint8_t LINK_INVALID = 1u << 1;
inline constexpr uint8_t UNCALIBRATED = 1u << 2;
inline constexpr uint8_t SOFT_LIMIT   = 1u << 3;
inline constexpr uint8_t HW_LIMIT     = 1u << 4;
inline constexpr uint8_t FROZEN       = 1u << 5;
}  // namespace JointDebugFlags

/// One joint row from firmware DebugPacket V1 (11 bytes on wire).
struct JointDebugEntry {
    uint8_t  online     = 0;  ///< 0=offline, 1=online
    uint16_t raw_u16    = 0;  ///< raw encoder SPI word
    float    angle_rad  = 0.f;
    uint8_t  comm_fail  = 0;
    uint8_t  flags      = 0;  ///< ``JointDebugFlags`` bits
    uint16_t fault_u16  = 0;
};

/// Parsed wired UDP debug stream sample (firmware DebugPacket V1, 294 B).
struct WiredUdpDebugSample {
    DeviceSide                              side              = DeviceSide::RIGHT;
    std::string                             sn;
    uint16_t                                seq               = 0;
    std::array<JointDebugEntry, 22>         joints{};
    int64_t                                 timestamp_ms      = 0;
    uint64_t                                wire_timestamp_us = 0;
};

struct DeviceInfo {
    std::string sn;
    std::string pn;
    /// Glove STM32 firmware version read from firmware identity / wired heartbeat.
    std::string glove_firmware_version;
    DeviceSide  device_side   = DeviceSide::RIGHT;
    DeviceType  device_type   = DeviceType::UNKNOWN;
    std::string ip;
    std::string product_name;
    float       hz            = 0;  ///< serial path only; not driven by UDP merge
    float       robot_hz      = 0;  ///< actual completed ROBOT retarget frames per second; not publish/cache replay rate
    int64_t     last_seen_at  = 0;  ///< Unix timestamp (ms)
    bool        online        = false;
    /// Fault diagnostics keyed by fault code. Wired path fills this from GET_DIAGNOSTICS / heartbeat
    /// debug details; wireless serial fills it from cmd=3 FAULT_CODE joint bitmasks.
    std::map<int, std::vector<int>> diagnostics;
    /// Compatibility summary fault code. Wireless serial uses the first non-zero code in the latest
    /// cmd=3 FAULT_CODE payload; use \ref diagnostics for the full fault set.
    uint32_t    error_code    = 0;
    /// Serial joint-report TDM ``BATTERY_LEVEL`` (id=1). ``nullopt`` until observed.
    std::optional<uint32_t> battery_level;
    /// Serial joint-report TDM ``UPTIME_MS`` (id=2). ``nullopt`` until observed.
    std::optional<uint32_t> uptime_ms;
    /// Serial joint-report TDM ``POWER`` (id=3). Raw pass-through until product semantics settle.
    std::optional<uint32_t> power;
    /// Serial joint-report TDM ``VIBRATION_LEVEL`` (id=4). Raw pass-through.
    std::optional<uint32_t> vibration_level;
    /// Wired HA4 heartbeat ``DeviceStatus`` (when present on wire).
    uint64_t    joint_lock_status  = 0;
    uint64_t    temperature_levels = 0;
    /// Serial cmd=0xFFFF per-slave record: 1s-window average RSSI in dBm (hand_wireless slave id 1=left, 2=right).
    std::optional<int8_t> rssi_avg;
    /// Serial cmd=0xFFFF Payload_0: nRF firmware version (e.g. "1.0.2"). Empty if unknown.
    std::string nrf_firmware_version;
    /// Serial cmd=0xFFFF Payload_0: pairing SET ID and RF channel (master-global).
    std::optional<uint32_t> set_id;
    std::optional<uint8_t>  channel;
};


// ============================================================================
//  AvatarDevice – per-device handle (unified interface for all device types)
// ============================================================================

/// Shared-ownership handle returned by AvatarSDK::get_device().
using DevicePtr = std::shared_ptr<AvatarDevice>;

class AvatarDevice {
public:
    ~AvatarDevice();
    AvatarDevice(const AvatarDevice&)            = delete;
    AvatarDevice& operator=(const AvatarDevice&) = delete;

    // ---- Lifecycle ----

    /** @brief One-time device initialisation.
     *  @param config_json  Device-specific config, or "{}" for defaults. */
    ErrorCode init   (const std::string& config_json);

    /** @brief Begin data streaming and background processing. */
    ErrorCode start  ();

    /** @brief Pause streaming; device remains connected. */
    ErrorCode stop   ();

    /** @brief Release all resources held by this handle. */
    void      destroy();

    // ---- Parameter plane ----

    /** @brief Write a named parameter.
     *  @param req_json  { "key": "...", "value": <any JSON> } */
    ErrorCode set_param(const std::string& req_json);

    /** @brief Read a named parameter.
     *  @param req_json  { "key": "..." }
     *  @return { ErrorCode, JSON: { "key": "...", "value": <any JSON> } } */
    std::pair<ErrorCode, std::string> get_param(const std::string& req_json);

    // ---- Task / system plane ----

    /** @brief Unified task command (calibration, OTA, 3D force, progress, …).
     *  @param req_json  JSON must include **"key"** (e.g. `zero_calib`, `start_upgrade`,
     *         `get_upgrade_progress`, `set_3d_force`, `clear_3d_force`, `stop_upgrade`).
     *  @return { ErrorCode, JSON payload; "{}" when no data; "" on some failures } */
    std::pair<ErrorCode, std::string> set_task(const std::string& req_json);

    // ---- Data plane ----

    /** @brief Check whether new serial data has arrived since the last fetch_data() call. */
    bool has_new_data() const;

    /** @brief Return an AvatarDataFrame for @a categery.
     *  RAW/HUMAN are built from the latest joint sample on the caller's thread.
     *  ROBOT mode is controlled by retarget_update_rate_hz:
     *  0 disables retarget,
     *  1..199 returns the latest async worker cache, and >=200 builds ROBOT
     *  synchronously on the caller's thread.
     *  @return ErrorCode::OPERATION_NOT_ALLOWED if start() was not called,
     *          ErrorCode::NO_VALID_DATA_RETURNED if no frame has been built yet. */
    ErrorCode fetch_data(AvatarDataFrame& frame,
                         DeviceDataCategery categery = DeviceDataCategery::RAW);

    /** @brief Build RAW and ROBOT frames from one underlying raw sample.
     *  Only valid when retarget_update_rate_hz is >=200. The
     *  returned ROBOT header inherits the RAW sample stamp and seq; sys_time is
     *  the frame generation time.
     */
    ErrorCode fetch_synced_robot_data(AvatarDataFrame& raw_frame,
                                      AvatarDataFrame& robot_frame);

    /** @brief Latest wired UDP debug packet for this device (ethernet_udp transport).
     *  @return false if no debug sample received yet. */
    bool fetch_debug_data(WiredUdpDebugSample& out);

    // ---- Identity ----

    /** @brief Snapshot of identity / discovery fields for this handle (includes ``diagnostics`` when populated). */
    DeviceInfo get_device_info() const;

    /** @brief Refresh cached identity fields after the serial path reads firmware params (sn, pn, firmware_version). */
    void set_firmware_serial_number(std::string sn);
    void set_firmware_identity(std::string sn, std::string pn, std::string glove_firmware_version);

    /** @name Internal (AvatarSDK wiring)
     * @{ */
    void internal_set_hand(std::unique_ptr<IHandDevice> hand);
    void internal_on_serial_data(const SerialDataSample& sample);
    void internal_on_serial_reconnected();
    void internal_on_wired_udp_data(const WiredUdpJointSample& sample);
    void internal_on_wired_udp_debug(const WiredUdpDebugSample& sample);
    void internal_set_glove_pn(const std::string& pn);
    /** @} */

private:
    friend class AvatarSDK;
    explicit AvatarDevice(const DeviceInfo& info);

    struct Impl;
    std::unique_ptr<Impl> impl_;
};

// ============================================================================
//  AvatarSDK – manager / process-wide singleton
// ============================================================================

class AvatarSDK {
public:
    /** @brief Process-wide singleton accessor. */
    static AvatarSDK& get_instance();

    ~AvatarSDK();
    AvatarSDK(const AvatarSDK&)            = delete;
    AvatarSDK& operator=(const AvatarSDK&) = delete;
    static const char* version() { return AVATAR_SDK_VERSION; }

    // ---- Lifecycle ----

    /** @brief Connect transport and start discovery + telemetry services.
     *  @param config_json  TransportConfig as JSON string; pass "{}" for defaults.
     *                      Empty/missing/non-JSON input falls back to defaults.
     *                      Optional `use_new_tactile_header` controls wired UDP
     *                      tactile Header_0 Reserved (true -> 1, false -> 0).
     *                      Optional `reserse_wave_tactile` is consumed by the Python
     *                      Wave bridge for slave-hand mapping; SDK task output
     *                      keeps the request order unchanged. */
    ErrorCode initialize(const std::string& config_json);

    /** @brief USB serial link state after `initialize()` / `destroy()` (see `UsbConnectionState`). */
    UsbConnectionState get_usb_connection_state() const;

    /** @brief Disconnect all devices, stop discovery/listeners, release transport. */
    void destroy();

    // ---- Device handles ----
    /** @brief All known devices, stable ascending order by ``device_side``. */
    std::vector<DeviceInfo> list_device_info() const;

    /** @brief Devices matching ``type``, stable ascending order by ``device_side``. */
    std::vector<DeviceInfo> list_device_info(DeviceType type) const;

    /** @brief First matching row from ``list_device_info(type)`` for ``side`` (see ``discover.md`` §2). */
    DevicePtr get_device(DeviceType type, DeviceSide side);

    // ---- Diagnostics ----
    /** @brief Log data-forward stats. One compact line:
     *  ``total_callbacks|elapsed_s|cur_s_frames HZ[Llast1s][Rlast1s]`` (left/right = last completed
     *  second frame counts). When inactive: ``idle n=…``. */
    void summary() const;

    /** @brief Same statistics as ``summary()`` as a single line (no I/O); for app logging. */
    std::string summary_text() const;

private:
    AvatarSDK();
    struct Impl;
    std::unique_ptr<Impl> impl_;
};

}  // namespace avatar

#ifndef SHARPA_SDK_H
void setup_cpp_logging(const std::string& log_filepath, bool console_log = true,
                       const std::string& log_level = "INFO");
#endif

#endif  // AVATAR_SDK_H
