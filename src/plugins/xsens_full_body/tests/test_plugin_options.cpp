// SPDX-FileCopyrightText: Copyright (c) 2026 Xsens Technologies B.V. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

// Standalone unit test for the Xsens full-body pusher's argument parsing. It asserts what each
// command line resolves to, so a defaulting, validation or precedence bug cannot pass silently.
//
// Needs no CloudXR runtime, no socket and no suit -- which is the point: the plugin itself
// cannot be constructed without an OpenXR session, so argument handling was previously
// reachable only through a live end-to-end run. Same reason test_frame_decision.cpp exists.
//
// Build & run standalone:
//   g++ -std=c++20 -I.. test_plugin_options.cpp ../plugin_options.cpp -o t && ./t

#include "plugin_options.hpp"

#include <cstdio>
#include <cstdlib>
#include <initializer_list>
#include <string>
#include <vector>

using namespace plugins::xsens_full_body;

namespace
{

int g_checks = 0;

#define CHECK(cond)                                                                                                    \
    do                                                                                                                 \
    {                                                                                                                  \
        ++g_checks;                                                                                                    \
        if (!(cond))                                                                                                   \
        {                                                                                                              \
            std::fprintf(stderr, "FAIL %s:%d: %s\n", __FILE__, __LINE__, #cond);                                       \
            std::abort();                                                                                              \
        }                                                                                                              \
    } while (0)

// ---------------------------------------------------------------------------------------------
// Harness: argv[0] is prepended for us, because a real one is always present and forgetting it
// silently shifts every argument by one.
// ---------------------------------------------------------------------------------------------

struct Parsed
{
    ParseOutcome outcome;
    XsensFullBodyOptions options;
    std::string error;
};

Parsed parse(std::initializer_list<const char*> args)
{
    std::vector<const char*> argv{ "xsens_full_body_plugin" };
    argv.insert(argv.end(), args.begin(), args.end());

    Parsed result;
    result.outcome = parse_options(static_cast<int>(argv.size()), argv.data(), result.options, result.error);
    return result;
}

//! An error, and one whose message names \a needle -- an operator who cannot see which argument
//! was rejected has to bisect the command line by hand.
void check_error_naming(const Parsed& p, const std::string& needle)
{
    CHECK(p.outcome == ParseOutcome::Error);
    CHECK(p.error.find(needle) != std::string::npos);
}

// ---------------------------------------------------------------------------------------------

void test_defaults()
{
    const Parsed p = parse({});
    CHECK(p.outcome == ParseOutcome::Ok);
    CHECK(p.options.collection_id == "xsens_full_body");
    CHECK(p.options.bind_address == "0.0.0.0");
    CHECK(p.options.udp_port == 9764);
    CHECK(p.options.max_flatbuffer_size == 4096);
    CHECK(!p.options.used_legacy_positionals);
    CHECK(p.error.empty());
}

void test_each_flag_alone()
{
    const Parsed collection = parse({ "--collection-id=other" });
    CHECK(collection.outcome == ParseOutcome::Ok);
    CHECK(collection.options.collection_id == "other");
    // The untouched fields keep their defaults rather than being reset alongside.
    CHECK(collection.options.bind_address == "0.0.0.0");
    CHECK(collection.options.udp_port == 9764);

    const Parsed address = parse({ "--address=127.0.0.1" });
    CHECK(address.outcome == ParseOutcome::Ok);
    CHECK(address.options.bind_address == "127.0.0.1");

    const Parsed port = parse({ "--port=1" });
    CHECK(port.outcome == ParseOutcome::Ok);
    CHECK(port.options.udp_port == 1);

    const Parsed size = parse({ "--max-flatbuffer-size=16384" });
    CHECK(size.outcome == ParseOutcome::Ok);
    CHECK(size.options.max_flatbuffer_size == 16384);
}

void test_all_flags_together()
{
    const Parsed p =
        parse({ "--collection-id=rig2", "--address=10.1.2.3", "--port=65535", "--max-flatbuffer-size=8192" });
    CHECK(p.outcome == ParseOutcome::Ok);
    CHECK(p.options.collection_id == "rig2");
    CHECK(p.options.bind_address == "10.1.2.3");
    CHECK(p.options.udp_port == 65535);
    CHECK(p.options.max_flatbuffer_size == 8192);
    CHECK(!p.options.used_legacy_positionals);
}

//! Regression: the launcher injects --plugin-root-id ahead of plugin.yaml's own arguments, and
//! a plugin that does not swallow it exits before it ever binds. That is the bug this fixes,
//! so every position it can arrive in is pinned.
void test_plugin_root_id_is_swallowed()
{
    const Parsed alone = parse({ "--plugin-root-id=abc" });
    CHECK(alone.outcome == ParseOutcome::Ok);
    CHECK(alone.options.collection_id == "xsens_full_body");
    CHECK(!alone.options.used_legacy_positionals);

    // The real launcher shape: injected first, then the yaml args.
    const Parsed launcher = parse({ "--plugin-root-id=abc", "--collection-id=rig", "--port=9000" });
    CHECK(launcher.outcome == ParseOutcome::Ok);
    CHECK(launcher.options.collection_id == "rig");
    CHECK(launcher.options.udp_port == 9000);

    const Parsed interleaved = parse({ "--collection-id=rig", "--plugin-root-id=abc", "--port=9000" });
    CHECK(interleaved.outcome == ParseOutcome::Ok);
    CHECK(interleaved.options.collection_id == "rig");
    CHECK(interleaved.options.udp_port == 9000);

    // Space-separated form: the value must not leak through as a positional.
    const Parsed spaced = parse({ "--plugin-root-id", "abc", "--port=9000" });
    CHECK(spaced.outcome == ParseOutcome::Ok);
    CHECK(spaced.options.udp_port == 9000);
    CHECK(!spaced.options.used_legacy_positionals);

    // Ahead of the deprecated positional form, it must not be taken for the collection id.
    const Parsed with_positionals = parse({ "--plugin-root-id=abc", "rig", "9000", "4096" });
    CHECK(with_positionals.outcome == ParseOutcome::Ok);
    CHECK(with_positionals.options.collection_id == "rig");
    CHECK(with_positionals.options.udp_port == 9000);
    CHECK(with_positionals.options.used_legacy_positionals);

    check_error_naming(parse({ "--plugin-root-id" }), "--plugin-root-id");
}

void test_legacy_positionals()
{
    const Parsed one = parse({ "rig" });
    CHECK(one.outcome == ParseOutcome::Ok);
    CHECK(one.options.collection_id == "rig");
    CHECK(one.options.udp_port == 9764);
    CHECK(one.options.max_flatbuffer_size == 4096);
    CHECK(one.options.used_legacy_positionals);

    const Parsed two = parse({ "rig", "9000" });
    CHECK(two.outcome == ParseOutcome::Ok);
    CHECK(two.options.udp_port == 9000);
    CHECK(two.options.max_flatbuffer_size == 4096);

    // The invocation the README and run/pipeline.sh have always used.
    const Parsed three = parse({ "xsens_full_body", "9764", "4096" });
    CHECK(three.outcome == ParseOutcome::Ok);
    CHECK(three.options.collection_id == "xsens_full_body");
    CHECK(three.options.udp_port == 9764);
    CHECK(three.options.max_flatbuffer_size == 4096);
    CHECK(three.options.used_legacy_positionals);
    // No positional ever sets the bind address -- that is flag-only by design.
    CHECK(three.options.bind_address == "0.0.0.0");

    CHECK(parse({ "rig", "9764", "4096", "extra" }).outcome == ParseOutcome::Error);
}

//! Mixing is an error rather than a precedence rule: a silently ignored argument here is a
//! pusher listening somewhere the operator did not ask for.
void test_flags_and_positionals_do_not_mix()
{
    check_error_naming(parse({ "--port=9000", "rig" }), "rig");
    // Leading positional wins the form, so the flag lands in the positional parser as a fourth
    // argument or an unparsable port -- either way it must not be silently applied.
    CHECK(parse({ "rig", "--port=9000" }).outcome == ParseOutcome::Error);
    CHECK(parse({ "rig", "9000", "4096", "--address=127.0.0.1" }).outcome == ParseOutcome::Error);
}

void test_invalid_port()
{
    for (const char* bad : { "--port=0", "--port=65536", "--port=abc", "--port=9764x", "--port=-1", "--port=" })
    {
        check_error_naming(parse({ bad }), "--port");
    }
    check_error_naming(parse({ "rig", "70000" }), "udp_port");
}

void test_invalid_max_flatbuffer_size()
{
    for (const char* bad : { "--max-flatbuffer-size=0", "--max-flatbuffer-size=abc", "--max-flatbuffer-size=4096b",
                             "--max-flatbuffer-size=" })
    {
        check_error_naming(parse({ bad }), "--max-flatbuffer-size");
    }
    check_error_naming(parse({ "rig", "9764", "0" }), "max_flatbuffer_size");
}

//! An unvalidated bind address fails as silent no-data, the same signature as a collection_id
//! mismatch -- so every near-miss shape is rejected at parse time instead.
void test_invalid_address()
{
    for (const char* bad :
         { "--address=999.1.1.1", "--address=localhost", "--address=", "--address=::1", "--address=127.0.0.1.1",
           "--address=127.0.0", "--address=127.0.0.1:9764", "--address=1.2.3.4 " })
    {
        check_error_naming(parse({ bad }), "--address");
    }

    // Accepted shapes, including the two that matter operationally.
    for (const char* good : { "--address=0.0.0.0", "--address=127.0.0.1", "--address=255.255.255.255" })
    {
        CHECK(parse({ good }).outcome == ParseOutcome::Ok);
    }
}

void test_empty_collection_id()
{
    check_error_naming(parse({ "--collection-id=" }), "collection_id");
    check_error_naming(parse({ "" }), "collection_id");
}

void test_unknown_flag()
{
    check_error_naming(parse({ "--frobnicate" }), "--frobnicate");
    check_error_naming(parse({ "--port=9000", "--frobnicate=1" }), "--frobnicate");
    // A near miss on a real flag is still unknown, not a partial match.
    check_error_naming(parse({ "--adress=127.0.0.1" }), "--adress");
    check_error_naming(parse({ "--port" }), "--port");
}

void test_help()
{
    CHECK(parse({ "--help" }).outcome == ParseOutcome::HelpRequested);
    CHECK(parse({ "-h" }).outcome == ParseOutcome::HelpRequested);
    CHECK(parse({ "--port=9000", "--help" }).outcome == ParseOutcome::HelpRequested);
    CHECK(parse({ "rig", "--help" }).outcome == ParseOutcome::HelpRequested);
    // Help wins over an otherwise-fatal command line: asking what the flags are is exactly what
    // an operator does after getting one wrong.
    CHECK(parse({ "--frobnicate", "--help" }).outcome == ParseOutcome::HelpRequested);
}

} // namespace

int main()
{
    test_defaults();
    test_each_flag_alone();
    test_all_flags_together();
    test_plugin_root_id_is_swallowed();
    test_legacy_positionals();
    test_flags_and_positionals_do_not_mix();
    test_invalid_port();
    test_invalid_max_flatbuffer_size();
    test_invalid_address();
    test_empty_collection_id();
    test_unknown_flag();
    test_help();

    std::printf("test_plugin_options: %d checks passed\n", g_checks);
    return 0;
}
