// SPDX-FileCopyrightText: Copyright (c) 2026 Xsens Technologies B.V. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#include "plugin_options.hpp"

#include <arpa/inet.h>
#include <netinet/in.h>
#include <sys/socket.h>

#include <charconv>
#include <string_view>
#include <vector>

namespace plugins
{
namespace xsens_full_body
{

namespace
{

constexpr std::string_view ROOT_ID_FLAG = "--plugin-root-id";
constexpr size_t MAX_POSITIONALS = 3;

bool starts_with(std::string_view text, std::string_view prefix)
{
    return text.size() >= prefix.size() && text.compare(0, prefix.size(), prefix) == 0;
}

//! Strict: rejects trailing garbage ("9764x") and zero, both of which `strtoul` would accept.
bool parse_size(std::string_view text, size_t& out)
{
    const char* begin = text.data();
    const char* end = begin + text.size();
    const auto [ptr, error] = std::from_chars(begin, end, out);
    return error == std::errc{} && ptr == end && out > 0;
}

bool parse_port(std::string_view text, uint16_t& out)
{
    size_t parsed = 0;
    if (!parse_size(text, parsed) || parsed > 65535)
    {
        return false;
    }
    out = static_cast<uint16_t>(parsed);
    return true;
}

//! Literal dotted-quad only -- deliberately not `getaddrinfo`. The socket is AF_INET, a bind
//! address should name an interface rather than a name to look up, and resolving a hostname to
//! an address this host does not own only defers the failure to a confusing EADDRNOTAVAIL.
bool valid_ipv4(const std::string& text)
{
    in_addr parsed{};
    return ::inet_pton(AF_INET, text.c_str(), &parsed) == 1;
}

ParseOutcome bad_value(const std::string& label, const std::string& value, std::string& error)
{
    error = "invalid " + label + " '" + value + "'";
    return ParseOutcome::Error;
}

ParseOutcome parse_collection_id(const std::string& value, XsensFullBodyOptions& out, std::string& error)
{
    // An empty rendezvous string would leave the reader hunting a collection that cannot be
    // named -- the silent-no-data failure, arrived at from the pusher side.
    if (value.empty())
    {
        error = "collection_id must not be empty";
        return ParseOutcome::Error;
    }
    out.collection_id = value;
    return ParseOutcome::Ok;
}

ParseOutcome parse_flag_form(const std::vector<std::string>& args, XsensFullBodyOptions& out, std::string& error)
{
    for (const std::string& arg : args)
    {
        if (!starts_with(arg, "--"))
        {
            error = "unexpected argument '" + arg + "' -- flags and the deprecated positional form cannot be mixed";
            return ParseOutcome::Error;
        }

        if (starts_with(arg, "--collection-id="))
        {
            if (parse_collection_id(arg.substr(16), out, error) != ParseOutcome::Ok)
            {
                return ParseOutcome::Error;
            }
        }
        else if (starts_with(arg, "--address="))
        {
            const std::string value = arg.substr(10);
            if (!valid_ipv4(value))
            {
                error =
                    "invalid --address '" + value + "' -- expected a literal IPv4 address such as 0.0.0.0 or 127.0.0.1";
                return ParseOutcome::Error;
            }
            out.bind_address = value;
        }
        else if (starts_with(arg, "--port="))
        {
            if (!parse_port(arg.substr(7), out.udp_port))
            {
                return bad_value("--port", arg.substr(7), error);
            }
        }
        else if (starts_with(arg, "--max-flatbuffer-size="))
        {
            if (!parse_size(arg.substr(22), out.max_flatbuffer_size))
            {
                return bad_value("--max-flatbuffer-size", arg.substr(22), error);
            }
        }
        else
        {
            error = "unknown option '" + arg + "'";
            return ParseOutcome::Error;
        }
    }
    return ParseOutcome::Ok;
}

ParseOutcome parse_positional_form(const std::vector<std::string>& args, XsensFullBodyOptions& out, std::string& error)
{
    if (args.size() > MAX_POSITIONALS)
    {
        error = "expected at most 3 positional arguments -- use the flag form for anything more";
        return ParseOutcome::Error;
    }

    out.used_legacy_positionals = true;

    if (parse_collection_id(args[0], out, error) != ParseOutcome::Ok)
    {
        return ParseOutcome::Error;
    }
    if (args.size() > 1 && !parse_port(args[1], out.udp_port))
    {
        return bad_value("udp_port", args[1], error);
    }
    if (args.size() > 2 && !parse_size(args[2], out.max_flatbuffer_size))
    {
        return bad_value("max_flatbuffer_size", args[2], error);
    }
    return ParseOutcome::Ok;
}

} // namespace

ParseOutcome parse_options(int argc, const char* const* argv, XsensFullBodyOptions& out, std::string& error)
{
    out = XsensFullBodyOptions{};
    error.clear();

    // --plugin-root-id is stripped first, in both spellings, so neither form below has to think
    // about it. The launcher injects it ahead of plugin.yaml's own arguments (see
    // core/plugin_manager/cpp/plugin.cpp), so a plugin that does not swallow it here sees a
    // stray argument and exits before it ever binds.
    std::vector<std::string> args;
    for (int i = 1; i < argc; ++i)
    {
        const std::string_view arg = argv[i];

        if (arg == ROOT_ID_FLAG)
        {
            if (i + 1 >= argc)
            {
                error = "--plugin-root-id requires a value";
                return ParseOutcome::Error;
            }
            ++i;
            continue;
        }
        if (starts_with(arg, "--plugin-root-id="))
        {
            continue;
        }
        if (arg == "--help" || arg == "-h")
        {
            return ParseOutcome::HelpRequested;
        }
        args.emplace_back(arg);
    }

    if (args.empty())
    {
        return ParseOutcome::Ok;
    }
    return starts_with(args.front(), "--") ? parse_flag_form(args, out, error) : parse_positional_form(args, out, error);
}

} // namespace xsens_full_body
} // namespace plugins
