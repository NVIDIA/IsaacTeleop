// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

// Standalone unit test for the OGLO packet parser. It builds packets using the
// firmware's own 12-bit packing reference and asserts that
// the parser is the exact inverse, so a decode bug cannot pass silently.
//
// Build & run standalone (no IsaacTeleop deps):
//   g++ -std=c++20 -I.. test_oglo_packet_parser.cpp ../oglo_packet_parser.cpp -o t && ./t

#include "oglo_packet_parser.hpp"

#include <cassert>
#include <cstdint>
#include <cstdio>
#include <cstdlib>
#include <vector>

using namespace plugins::oglo_tactile;

namespace
{

void put_u16(std::vector<uint8_t>& b, uint16_t v)
{
    b.push_back(static_cast<uint8_t>(v & 0xFF));
    b.push_back(static_cast<uint8_t>((v >> 8) & 0xFF));
}

void put_u32(std::vector<uint8_t>& b, uint32_t v)
{
    b.push_back(static_cast<uint8_t>(v & 0xFF));
    b.push_back(static_cast<uint8_t>((v >> 8) & 0xFF));
    b.push_back(static_cast<uint8_t>((v >> 16) & 0xFF));
    b.push_back(static_cast<uint8_t>((v >> 24) & 0xFF));
}

void put_i16(std::vector<uint8_t>& b, int16_t v)
{
    put_u16(b, static_cast<uint16_t>(v));
}

// Firmware-side 12-bit pack reference (OGLO packed12-v5):
//   b0 = a >> 4; b1 = ((a & 0x0F) << 4) | (b >> 8); b2 = b & 0xFF
void pack_taxels12(const uint16_t taxels[kNumTaxels], std::vector<uint8_t>& b)
{
    for (int k = 0; k < kNumTaxels / 2; ++k)
    {
        const uint16_t a = taxels[2 * k + 0] & 0x0FFF;
        const uint16_t c = taxels[2 * k + 1] & 0x0FFF;
        b.push_back(static_cast<uint8_t>(a >> 4));
        b.push_back(static_cast<uint8_t>(((a & 0x0F) << 4) | (c >> 8)));
        b.push_back(static_cast<uint8_t>(c & 0xFF));
    }
}

// Deterministic synthetic taxel pattern spanning the full 12-bit range.
uint16_t synth_taxel(int sample, int idx)
{
    return static_cast<uint16_t>((idx * 53 + sample * 911 + 7) % 4096);
}

int g_checks = 0;
void check(bool cond, const char* msg)
{
    ++g_checks;
    if (!cond)
    {
        std::fprintf(stderr, "FAIL: %s\n", msg);
        std::abort();
    }
}

// ---- packed12 v5 round-trip --------------------------------------------------
void test_packed12_v5()
{
    const uint8_t count = 3;
    const uint32_t seq_base = 1000;
    const uint32_t t_base_us = 5'000'000;
    const uint16_t dt[3] = { 0, 10000, 20000 };

    std::vector<uint8_t> pkt;
    pkt.push_back(count);
    pkt.push_back(0x04); // flags: packed12 v5
    put_u32(pkt, seq_base);
    put_u32(pkt, t_base_us);

    uint16_t expected_taxels[3][kNumTaxels];
    for (int s = 0; s < count; ++s)
    {
        put_u16(pkt, dt[s]);
        for (int i = 0; i < kNumTaxels; ++i)
            expected_taxels[s][i] = synth_taxel(s, i);
        pack_taxels12(expected_taxels[s], pkt);
        // IMU raw: ax,ay,az,gx,gy,gz
        put_i16(pkt, static_cast<int16_t>(100 + s));
        put_i16(pkt, static_cast<int16_t>(-200 - s));
        put_i16(pkt, static_cast<int16_t>(4096 - s));
        put_i16(pkt, static_cast<int16_t>(s));
        put_i16(pkt, static_cast<int16_t>(-s));
        put_i16(pkt, static_cast<int16_t>(s * 7));
    }

    check(pkt.size() == 10u + 3u * 134u, "v5 packet size == 412");

    std::vector<GloveSample> out;
    check(PacketParser::parse(pkt.data(), pkt.size(), kNumTaxels, out), "v5 parse ok");
    check(out.size() == count, "v5 sample count");

    for (int s = 0; s < count; ++s)
    {
        check(out[s].seq == seq_base + static_cast<uint32_t>(s), "v5 seq");
        check(out[s].device_time_us == t_base_us + dt[s], "v5 device_time_us");
        for (int i = 0; i < kNumTaxels; ++i)
            check(out[s].taxels[i] == expected_taxels[s][i], "v5 taxel value");
        check(out[s].imu.ax == static_cast<int16_t>(100 + s), "v5 imu ax");
        check(out[s].imu.ay == static_cast<int16_t>(-200 - s), "v5 imu ay");
        check(out[s].imu.az == static_cast<int16_t>(4096 - s), "v5 imu az");
        check(out[s].imu.gz == static_cast<int16_t>(s * 7), "v5 imu gz");
    }
}

// ---- packed12 12-bit unpack edge values --------------------------------------
void test_unpack_edges()
{
    uint16_t taxels[kNumTaxels];
    for (int i = 0; i < kNumTaxels; ++i)
        taxels[i] = (i % 2 == 0) ? 4095 : 0; // alternating max / min

    std::vector<uint8_t> packed;
    pack_taxels12(taxels, packed);
    check(packed.size() == 120u, "packed block == 120 bytes");

    std::array<uint16_t, kNumTaxels> got{};
    PacketParser::unpack_taxels12(packed.data(), got);
    for (int i = 0; i < kNumTaxels; ++i)
        check(got[i] == taxels[i], "unpack edge value");
}

// ---- schema-4 Method B fallback ---------------------------------------------
void test_method_b()
{
    const uint8_t count = 2;
    const uint32_t base_ts = 1234;

    std::vector<uint8_t> pkt;
    pkt.push_back(count);
    pkt.push_back(0x01); // flags: Method B
    put_u32(pkt, base_ts);

    for (int s = 0; s < count; ++s)
    {
        for (int i = 0; i < kNumTaxels; ++i)
            put_u16(pkt, static_cast<uint16_t>((i + s) % 4096));
        // 17B IMU: roll,pitch,ax,ay,az,gx,gy,gz (i16) + ok(u8)
        put_i16(pkt, 11); // roll (ignored)
        put_i16(pkt, 22); // pitch (ignored)
        put_i16(pkt, static_cast<int16_t>(s)); // ax
        put_i16(pkt, static_cast<int16_t>(-s)); // ay
        put_i16(pkt, 333); // az
        put_i16(pkt, 1); // gx
        put_i16(pkt, 2); // gy
        put_i16(pkt, 3); // gz
        pkt.push_back(1); // ok
    }

    std::vector<GloveSample> out;
    check(PacketParser::parse(pkt.data(), pkt.size(), kNumTaxels, out), "methodB parse ok");
    check(out.size() == count, "methodB sample count");
    check(out[0].taxels[0] == 0 && out[1].taxels[0] == 1, "methodB taxel");
    check(out[0].imu.az == 333 && out[0].imu.gz == 3, "methodB imu (roll/pitch skipped)");
}

// ---- robustness: truncated / unknown -----------------------------------------
void test_malformed()
{
    std::vector<GloveSample> out;
    const uint8_t too_short[] = { 0x03 };
    check(!PacketParser::parse(too_short, sizeof(too_short), kNumTaxels, out), "reject 1-byte packet");

    const uint8_t unknown_flags[] = { 0x01, 0x00, 0, 0, 0, 0 };
    check(!PacketParser::parse(unknown_flags, sizeof(unknown_flags), kNumTaxels, out), "reject unknown flags");

    // v5 header claims 3 samples but body is missing.
    std::vector<uint8_t> truncated = { 0x03, 0x04, 0, 0, 0, 0, 0, 0, 0, 0 };
    check(!PacketParser::parse(truncated.data(), truncated.size(), kNumTaxels, out), "reject truncated v5 body");
    check(out.empty(), "out untouched on failure");
}

} // namespace

int main()
{
    test_unpack_edges();
    test_packed12_v5();
    test_method_b();
    test_malformed();
    std::printf("OK: all %d checks passed\n", g_checks);
    return 0;
}
