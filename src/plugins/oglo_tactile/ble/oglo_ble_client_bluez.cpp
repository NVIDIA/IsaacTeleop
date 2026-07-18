// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

// Default OGLO BLE backend: talks to BlueZ directly over its D-Bus API using
// libdbus. libdbus is licensed under AFL-2.1 OR GPL-2.0; we use it under the
// permissive AFL-2.1, so the plugin carries no copyleft dependency. The only
// system requirement is the BlueZ D-Bus daemon plus libdbus-1 (apt:
// libdbus-1-dev), both already standard on any Linux host running Bluetooth.
//
// BlueZ exposes adapters, devices and GATT attributes as D-Bus objects under the
// well-known name org.bluez. The connection flow used here mirrors `bluetoothctl`:
//   1. find an adapter (org.bluez.Adapter1) and StartDiscovery
//   2. scan ObjectManager for a Device1 whose name matches the target glove
//   3. Device1.Connect(), wait for ServicesResolved
//   4. resolve the notify/config GATT characteristics by UUID
//   5. read the Config characteristic, then StartNotify and dispatch the
//      PropertiesChanged(Value) signals on a dedicated thread.

#include "oglo_ble_client.hpp"

#include <dbus/dbus.h>

#include <algorithm>
#include <atomic>
#include <cctype>
#include <chrono>
#include <cstring>
#include <stdexcept>
#include <thread>

namespace plugins
{
namespace oglo_tactile
{

namespace
{

constexpr const char* kBluez = "org.bluez";
constexpr const char* kObjMgr = "org.freedesktop.DBus.ObjectManager";
constexpr const char* kProps = "org.freedesktop.DBus.Properties";
constexpr const char* kAdapterIface = "org.bluez.Adapter1";
constexpr const char* kDeviceIface = "org.bluez.Device1";
constexpr const char* kGattCharIface = "org.bluez.GattCharacteristic1";

std::string to_upper(std::string s)
{
    std::transform(s.begin(), s.end(), s.begin(), [](unsigned char c) { return static_cast<char>(std::toupper(c)); });
    return s;
}

bool name_matches(const std::string& identifier, const std::string& target)
{
    return to_upper(identifier).find(to_upper(target)) != std::string::npos;
}

bool uuid_equals(const std::string& a, const std::string& b)
{
    return to_upper(a) == to_upper(b);
}

//! RAII wrapper for a DBusError so callers never leak the message string.
struct ScopedError
{
    DBusError err;
    ScopedError()
    {
        dbus_error_init(&err);
    }
    ~ScopedError()
    {
        dbus_error_free(&err);
    }
    bool is_set() const
    {
        return dbus_error_is_set(&err);
    }
    std::string message() const
    {
        return err.message ? err.message : "unknown D-Bus error";
    }
};

//! RAII wrapper for a DBusMessage* reply.
struct ScopedMessage
{
    DBusMessage* msg = nullptr;
    explicit ScopedMessage(DBusMessage* m = nullptr) : msg(m)
    {
    }
    ~ScopedMessage()
    {
        if (msg)
            dbus_message_unref(msg);
    }
    ScopedMessage(const ScopedMessage&) = delete;
    ScopedMessage& operator=(const ScopedMessage&) = delete;
    explicit operator bool() const
    {
        return msg != nullptr;
    }
};

//! Send a method call and block for the reply (BlueZ object under org.bluez).
//! @throws std::runtime_error with the D-Bus error message on failure.
DBusMessage* call_blocking(DBusConnection* conn,
                           const std::string& path,
                           const char* iface,
                           const char* method,
                           DBusMessage* with_args = nullptr,
                           int timeout_ms = 20000)
{
    DBusMessage* msg = with_args ? with_args : dbus_message_new_method_call(kBluez, path.c_str(), iface, method);
    if (!msg)
        throw std::runtime_error("OGLO BlueZ: out of memory building D-Bus call");

    ScopedError err;
    DBusMessage* reply = dbus_connection_send_with_reply_and_block(conn, msg, timeout_ms, &err.err);
    dbus_message_unref(msg);
    if (err.is_set() || !reply)
        throw std::runtime_error("OGLO BlueZ: " + std::string(method) + " failed: " + err.message());
    return reply;
}

//! Append an empty a{sv} options dict (required by ReadValue / StartNotify args).
void append_empty_options(DBusMessage* msg)
{
    DBusMessageIter args, dict;
    dbus_message_iter_init_append(msg, &args);
    dbus_message_iter_open_container(&args, DBUS_TYPE_ARRAY, "{sv}", &dict);
    dbus_message_iter_close_container(&args, &dict);
}

//! Pull a fixed byte array (ay) out of the iterator currently pointing at it.
void read_byte_array(DBusMessageIter* arr_iter, std::vector<uint8_t>& out)
{
    out.clear();
    if (dbus_message_iter_get_arg_type(arr_iter) != DBUS_TYPE_ARRAY)
        return;
    int n = 0;
    const uint8_t* data = nullptr;
    dbus_message_iter_get_fixed_array(arr_iter, &data, &n);
    if (data && n > 0)
        out.assign(data, data + n);
}

//! Within an a{sv} props iterator, find @p key and leave @p value_out recursed
//! into its variant payload. Returns false if the key is absent.
bool find_prop_variant(DBusMessageIter props_iter, const char* key, DBusMessageIter* value_out)
{
    while (dbus_message_iter_get_arg_type(&props_iter) == DBUS_TYPE_DICT_ENTRY)
    {
        DBusMessageIter entry;
        dbus_message_iter_recurse(&props_iter, &entry);
        const char* name = nullptr;
        if (dbus_message_iter_get_arg_type(&entry) == DBUS_TYPE_STRING)
            dbus_message_iter_get_basic(&entry, &name);
        dbus_message_iter_next(&entry); // -> variant
        if (name && std::strcmp(name, key) == 0)
        {
            dbus_message_iter_recurse(&entry, value_out); // into the variant payload
            return true;
        }
        dbus_message_iter_next(&props_iter);
    }
    return false;
}

bool prop_get_string(DBusMessageIter props_iter, const char* key, std::string& out)
{
    DBusMessageIter v;
    if (!find_prop_variant(props_iter, key, &v) || dbus_message_iter_get_arg_type(&v) != DBUS_TYPE_STRING)
        return false;
    const char* s = nullptr;
    dbus_message_iter_get_basic(&v, &s);
    out = s ? s : "";
    return true;
}

bool prop_get_bool(DBusMessageIter props_iter, const char* key, bool& out)
{
    DBusMessageIter v;
    if (!find_prop_variant(props_iter, key, &v) || dbus_message_iter_get_arg_type(&v) != DBUS_TYPE_BOOLEAN)
        return false;
    dbus_bool_t b = FALSE;
    dbus_message_iter_get_basic(&v, &b);
    out = b == TRUE;
    return true;
}

//! Visit every (object_path, interface_name, props-iter) from GetManagedObjects.
//! The props iterator passed to @p visit is positioned at the start of the
//! interface's a{sv} and may be copied freely by the visitor.
template <typename Visitor>
void walk_managed_objects(DBusConnection* conn, const Visitor& visit)
{
    ScopedMessage reply(call_blocking(conn, "/", kObjMgr, "GetManagedObjects"));
    DBusMessageIter root; // a{oa{sa{sv}}}
    if (!dbus_message_iter_init(reply.msg, &root) || dbus_message_iter_get_arg_type(&root) != DBUS_TYPE_ARRAY)
        return;

    DBusMessageIter objs;
    dbus_message_iter_recurse(&root, &objs);
    while (dbus_message_iter_get_arg_type(&objs) == DBUS_TYPE_DICT_ENTRY)
    {
        DBusMessageIter obj; // { o, a{sa{sv}} }
        dbus_message_iter_recurse(&objs, &obj);
        const char* obj_path = nullptr;
        if (dbus_message_iter_get_arg_type(&obj) == DBUS_TYPE_OBJECT_PATH)
            dbus_message_iter_get_basic(&obj, &obj_path);
        dbus_message_iter_next(&obj); // -> a{sa{sv}} (interfaces)

        DBusMessageIter ifaces;
        dbus_message_iter_recurse(&obj, &ifaces);
        while (dbus_message_iter_get_arg_type(&ifaces) == DBUS_TYPE_DICT_ENTRY)
        {
            DBusMessageIter iface; // { s, a{sv} }
            dbus_message_iter_recurse(&ifaces, &iface);
            const char* iface_name = nullptr;
            if (dbus_message_iter_get_arg_type(&iface) == DBUS_TYPE_STRING)
                dbus_message_iter_get_basic(&iface, &iface_name);
            dbus_message_iter_next(&iface); // -> a{sv} (props)

            DBusMessageIter props;
            dbus_message_iter_recurse(&iface, &props);
            if (obj_path && iface_name)
                visit(std::string(obj_path), std::string(iface_name), props);

            dbus_message_iter_next(&ifaces);
        }
        dbus_message_iter_next(&objs);
    }
}

class BlueZClient final : public OgloBleClient
{
public:
    explicit BlueZClient(std::string device_name_override) : m_name_override(std::move(device_name_override))
    {
        dbus_threads_init_default(); // backend touches the connection from two threads (never concurrently)
    }

    ~BlueZClient() override
    {
        try
        {
            disconnect();
        }
        catch (...)
        {
        }
        if (m_conn)
        {
            dbus_connection_close(m_conn);
            dbus_connection_unref(m_conn);
        }
    }

    std::string connect(Side side, std::chrono::milliseconds timeout) override
    {
        const std::string target = m_name_override.empty() ? advertised_name_for(side) : m_name_override;
        ensure_connection();

        m_adapter_path = find_adapter();
        if (m_adapter_path.empty())
            throw std::runtime_error("OGLO BlueZ: no Bluetooth adapter (org.bluez.Adapter1) found");

        set_le_discovery_filter();
        start_discovery();

        m_device_path = scan_for_device(target, timeout);
        stop_discovery();
        if (m_device_path.empty())
            throw std::runtime_error("OGLO BlueZ: '" + target + "' not found within scan timeout");

        connect_device(timeout);
        wait_services_resolved(timeout);
        resolve_characteristics();
        if (m_notify_char_path.empty() || m_config_char_path.empty())
            throw std::runtime_error("OGLO BlueZ: notify/config GATT characteristics not found on device");

        std::vector<uint8_t> config = read_characteristic(m_config_char_path);
        notify_state(true);
        return std::string(reinterpret_cast<const char*>(config.data()), config.size());
    }

    void subscribe(NotifyCallback cb) override
    {
        if (!m_conn || m_notify_char_path.empty())
            throw std::runtime_error("OGLO BlueZ: subscribe before connect");

        m_notify_cb = std::move(cb);

        // Receive PropertiesChanged for our notify characteristic and device.
        ScopedError err;
        const std::string rule =
            "type='signal',sender='org.bluez',interface='" + std::string(kProps) + "',member='PropertiesChanged'";
        dbus_bus_add_match(m_conn, rule.c_str(), &err.err);
        if (err.is_set())
            throw std::runtime_error("OGLO BlueZ: add_match failed: " + err.message());
        if (!dbus_connection_add_filter(m_conn, &BlueZClient::signal_filter, this, nullptr))
            throw std::runtime_error("OGLO BlueZ: add_filter failed (out of memory)");
        m_match_rule = rule;
        dbus_connection_flush(m_conn);

        {
            ScopedMessage start(call_blocking(m_conn, m_notify_char_path, kGattCharIface, "StartNotify"));
        }

        // Dispatch incoming notify signals on a dedicated thread so the consumer
        // thread (run()) is free to drain the queue and run the watchdog.
        m_dispatch_run.store(true, std::memory_order_relaxed);
        m_dispatch_thread = std::thread([this] { dispatch_loop(); });
    }

    void on_state_change(StateCallback cb) override
    {
        m_state_cb = std::move(cb);
    }

    void disconnect() override
    {
        // Quiescence contract: stop and join the dispatch thread first so the
        // NotifyCallback can never fire again, then tear the link down. After
        // this returns the connection is touched by this thread only.
        m_dispatch_run.store(false, std::memory_order_relaxed);
        if (m_dispatch_thread.joinable())
            m_dispatch_thread.join();

        if (m_conn)
        {
            dbus_connection_remove_filter(m_conn, &BlueZClient::signal_filter, this);
            if (!m_match_rule.empty())
            {
                ScopedError err;
                dbus_bus_remove_match(m_conn, m_match_rule.c_str(), &err.err);
                m_match_rule.clear();
            }
            stop_notify_best_effort();
            disconnect_device_best_effort();
        }
        m_notify_char_path.clear();
        m_config_char_path.clear();
    }

private:
    void ensure_connection()
    {
        if (m_conn)
            return;
        ScopedError err;
        m_conn = dbus_bus_get_private(DBUS_BUS_SYSTEM, &err.err);
        if (err.is_set() || !m_conn)
            throw std::runtime_error("OGLO BlueZ: cannot reach the system D-Bus / BlueZ daemon: " + err.message());
        // We dispatch the connection ourselves; don't let libdbus exit the process.
        dbus_connection_set_exit_on_disconnect(m_conn, FALSE);
    }

    std::string find_adapter()
    {
        std::string adapter;
        walk_managed_objects(m_conn,
                             [&](const std::string& path, const std::string& iface, DBusMessageIter)
                             {
                                 if (adapter.empty() && iface == kAdapterIface)
                                     adapter = path;
                             });
        return adapter;
    }

    void set_le_discovery_filter()
    {
        // Restrict discovery to LE so we converge faster and don't pick up BR/EDR
        // duplicates. Best-effort: ignore failures (older BlueZ may reject keys).
        try
        {
            DBusMessage* msg =
                dbus_message_new_method_call(kBluez, m_adapter_path.c_str(), kAdapterIface, "SetDiscoveryFilter");
            if (!msg)
                return;
            DBusMessageIter args, dict, entry, var;
            dbus_message_iter_init_append(msg, &args);
            dbus_message_iter_open_container(&args, DBUS_TYPE_ARRAY, "{sv}", &dict);
            dbus_message_iter_open_container(&dict, DBUS_TYPE_DICT_ENTRY, nullptr, &entry);
            const char* key = "Transport";
            const char* val = "le";
            dbus_message_iter_append_basic(&entry, DBUS_TYPE_STRING, &key);
            dbus_message_iter_open_container(&entry, DBUS_TYPE_VARIANT, "s", &var);
            dbus_message_iter_append_basic(&var, DBUS_TYPE_STRING, &val);
            dbus_message_iter_close_container(&entry, &var);
            dbus_message_iter_close_container(&dict, &entry);
            dbus_message_iter_close_container(&args, &dict);
            ScopedMessage reply(call_blocking(m_conn, m_adapter_path, kAdapterIface, "SetDiscoveryFilter", msg));
        }
        catch (const std::exception&)
        {
            // Non-fatal; discovery still works with the default filter.
        }
    }

    void start_discovery()
    {
        ScopedMessage reply(call_blocking(m_conn, m_adapter_path, kAdapterIface, "StartDiscovery"));
    }

    void stop_discovery()
    {
        try
        {
            ScopedMessage reply(call_blocking(m_conn, m_adapter_path, kAdapterIface, "StopDiscovery"));
        }
        catch (const std::exception&)
        {
            // Already stopped / adapter busy — harmless.
        }
    }

    std::string scan_for_device(const std::string& target, std::chrono::milliseconds timeout)
    {
        const auto deadline = std::chrono::steady_clock::now() + timeout;
        while (std::chrono::steady_clock::now() < deadline)
        {
            std::string match;
            walk_managed_objects(m_conn,
                                 [&](const std::string& path, const std::string& iface, DBusMessageIter props)
                                 {
                                     if (!match.empty() || iface != kDeviceIface)
                                         return;
                                     std::string name;
                                     if ((prop_get_string(props, "Alias", name) || prop_get_string(props, "Name", name)) &&
                                         name_matches(name, target))
                                         match = path;
                                 });
            if (!match.empty())
                return match;
            std::this_thread::sleep_for(std::chrono::milliseconds(200));
        }
        return "";
    }

    void connect_device(std::chrono::milliseconds timeout)
    {
        const int timeout_ms = static_cast<int>(std::max<long long>(timeout.count(), 20000));
        ScopedMessage reply(call_blocking(m_conn, m_device_path, kDeviceIface, "Connect", nullptr, timeout_ms));
    }

    void wait_services_resolved(std::chrono::milliseconds timeout)
    {
        const auto deadline = std::chrono::steady_clock::now() + timeout;
        while (std::chrono::steady_clock::now() < deadline)
        {
            bool resolved = false;
            walk_managed_objects(m_conn,
                                 [&](const std::string& path, const std::string& iface, DBusMessageIter props)
                                 {
                                     if (path == m_device_path && iface == kDeviceIface)
                                         prop_get_bool(props, "ServicesResolved", resolved);
                                 });
            if (resolved)
                return;
            std::this_thread::sleep_for(std::chrono::milliseconds(100));
        }
        throw std::runtime_error("OGLO BlueZ: GATT services did not resolve before timeout");
    }

    void resolve_characteristics()
    {
        m_notify_char_path.clear();
        m_config_char_path.clear();
        walk_managed_objects(m_conn,
                             [&](const std::string& path, const std::string& iface, DBusMessageIter props)
                             {
                                 if (iface != kGattCharIface || path.rfind(m_device_path, 0) != 0)
                                     return;
                                 std::string uuid;
                                 if (!prop_get_string(props, "UUID", uuid))
                                     return;
                                 if (uuid_equals(uuid, ble_uuids::kNotify))
                                     m_notify_char_path = path;
                                 else if (uuid_equals(uuid, ble_uuids::kConfig))
                                     m_config_char_path = path;
                             });
    }

    std::vector<uint8_t> read_characteristic(const std::string& char_path)
    {
        DBusMessage* msg = dbus_message_new_method_call(kBluez, char_path.c_str(), kGattCharIface, "ReadValue");
        if (!msg)
            throw std::runtime_error("OGLO BlueZ: out of memory building ReadValue");
        append_empty_options(msg);
        ScopedMessage reply(call_blocking(m_conn, char_path, kGattCharIface, "ReadValue", msg));

        DBusMessageIter it;
        std::vector<uint8_t> out;
        if (dbus_message_iter_init(reply.msg, &it))
            read_byte_array(&it, out);
        return out;
    }

    void stop_notify_best_effort()
    {
        if (m_notify_char_path.empty())
            return;
        try
        {
            ScopedMessage reply(call_blocking(m_conn, m_notify_char_path, kGattCharIface, "StopNotify"));
        }
        catch (const std::exception&)
        {
        }
    }

    void disconnect_device_best_effort()
    {
        if (m_device_path.empty())
            return;
        try
        {
            ScopedMessage reply(call_blocking(m_conn, m_device_path, kDeviceIface, "Disconnect"));
        }
        catch (const std::exception&)
        {
        }
    }

    void notify_state(bool connected)
    {
        if (m_state_cb)
            m_state_cb(connected);
    }

    void dispatch_loop()
    {
        // Pump the private connection: read_write_dispatch drives the filter,
        // which forwards notify payloads. 100 ms wakeups keep shutdown responsive.
        while (m_dispatch_run.load(std::memory_order_relaxed))
        {
            if (!dbus_connection_read_write_dispatch(m_conn, 100))
                break; // connection closed
        }
    }

    //! D-Bus filter (runs on the dispatch thread). Forwards notify-characteristic
    //! Value updates to the NotifyCallback and tracks device disconnects.
    static DBusHandlerResult signal_filter(DBusConnection*, DBusMessage* msg, void* user)
    {
        auto* self = static_cast<BlueZClient*>(user);
        if (!dbus_message_is_signal(msg, kProps, "PropertiesChanged"))
            return DBUS_HANDLER_RESULT_NOT_YET_HANDLED;

        const char* path = dbus_message_get_path(msg);
        if (!path)
            return DBUS_HANDLER_RESULT_NOT_YET_HANDLED;

        DBusMessageIter it; // (s interface, a{sv} changed, as invalidated)
        if (!dbus_message_iter_init(msg, &it) || dbus_message_iter_get_arg_type(&it) != DBUS_TYPE_STRING)
            return DBUS_HANDLER_RESULT_NOT_YET_HANDLED;
        const char* iface = nullptr;
        dbus_message_iter_get_basic(&it, &iface);
        dbus_message_iter_next(&it); // -> a{sv} changed
        if (dbus_message_iter_get_arg_type(&it) != DBUS_TYPE_ARRAY)
            return DBUS_HANDLER_RESULT_NOT_YET_HANDLED;
        DBusMessageIter changed;
        dbus_message_iter_recurse(&it, &changed);

        if (iface && std::strcmp(iface, kGattCharIface) == 0 && self->m_notify_char_path == path)
        {
            DBusMessageIter value;
            if (find_prop_variant(changed, "Value", &value))
            {
                std::vector<uint8_t> bytes;
                read_byte_array(&value, bytes);
                if (!bytes.empty() && self->m_notify_cb)
                    self->m_notify_cb(bytes.data(), bytes.size());
            }
            return DBUS_HANDLER_RESULT_HANDLED;
        }

        if (iface && std::strcmp(iface, kDeviceIface) == 0 && self->m_device_path == path)
        {
            bool connected = true;
            if (prop_get_bool(changed, "Connected", connected) && !connected)
                self->notify_state(false);
        }
        return DBUS_HANDLER_RESULT_NOT_YET_HANDLED;
    }

    std::string m_name_override;
    DBusConnection* m_conn = nullptr;
    std::string m_adapter_path;
    std::string m_device_path;
    std::string m_notify_char_path;
    std::string m_config_char_path;
    std::string m_match_rule;

    NotifyCallback m_notify_cb;
    StateCallback m_state_cb;

    std::thread m_dispatch_thread;
    std::atomic<bool> m_dispatch_run{ false };
};

} // namespace

std::unique_ptr<OgloBleClient> make_ble_client(std::string device_name_override)
{
    return std::make_unique<BlueZClient>(std::move(device_name_override));
}

} // namespace oglo_tactile
} // namespace plugins
