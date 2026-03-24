# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""PC-side UDP-over-TCP relay for tunneling CloudXR media (UDP) through ``adb reverse`` (TCP-only).

Framing protocol (shared with the headset-side Go relay):
each UDP datagram is sent on the TCP stream as ``[2-byte big-endian length][payload]``.
Both directions use the same framing on a single bidirectional TCP connection.
"""

from __future__ import annotations

import asyncio
import logging
import os
import struct

log = logging.getLogger("udp-tcp-relay")

DEFAULT_RELAY_TCP_PORT = 47999
DEFAULT_UDP_TARGET_PORT = 47998
DEFAULT_UDP_TARGET_HOST = "127.0.0.1"

_HEADER = struct.Struct("!H")  # 2-byte big-endian uint16
_MAX_UDP_PAYLOAD = 65535


def relay_tcp_port() -> int:
    raw = os.environ.get("TELEOP_UDP_RELAY_PORT", "").strip()
    if raw:
        return int(raw)
    return DEFAULT_RELAY_TCP_PORT


class _RelaySession:
    """Bridges one TCP connection to a UDP socket targeting the CloudXR runtime."""

    def __init__(
        self,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
        udp_host: str,
        udp_port: int,
        loop: asyncio.AbstractEventLoop,
    ) -> None:
        self._reader = reader
        self._writer = writer
        self._udp_host = udp_host
        self._udp_port = udp_port
        self._loop = loop
        self._udp_transport: asyncio.DatagramTransport | None = None
        self._tasks: list[asyncio.Task] = []
        self._closed = False

    async def run(self) -> None:
        transport, _protocol = await self._loop.create_datagram_endpoint(
            lambda: _UdpReceiver(self),
            remote_addr=(self._udp_host, self._udp_port),
        )
        self._udp_transport = transport
        try:
            tcp_task = asyncio.create_task(self._tcp_to_udp())
            self._tasks.append(tcp_task)
            await tcp_task
        finally:
            self.close()

    async def _tcp_to_udp(self) -> None:
        """Read length-prefixed datagrams from TCP, send as UDP."""
        try:
            while not self._closed:
                hdr = await self._reader.readexactly(_HEADER.size)
                (length,) = _HEADER.unpack(hdr)
                if length == 0:
                    continue
                payload = await self._reader.readexactly(length)
                if self._udp_transport and not self._closed:
                    self._udp_transport.sendto(payload)
        except asyncio.IncompleteReadError:
            log.debug("TCP peer disconnected (incomplete read)")
        except ConnectionResetError:
            log.debug("TCP connection reset")
        except Exception:
            if not self._closed:
                log.exception("tcp_to_udp error")

    def udp_datagram_received(self, data: bytes) -> None:
        """Called by _UdpReceiver when a UDP packet arrives from the runtime."""
        if self._closed or self._writer.is_closing():
            return
        if len(data) > _MAX_UDP_PAYLOAD:
            log.warning("Dropping oversized UDP datagram (%d bytes)", len(data))
            return
        frame = _HEADER.pack(len(data)) + data
        try:
            self._writer.write(frame)
        except Exception:
            if not self._closed:
                log.debug("Failed to write UDP->TCP frame")

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        for t in self._tasks:
            t.cancel()
        if self._udp_transport:
            self._udp_transport.close()
        if not self._writer.is_closing():
            self._writer.close()


class _UdpReceiver(asyncio.DatagramProtocol):
    def __init__(self, session: _RelaySession) -> None:
        self._session = session

    def datagram_received(self, data: bytes, addr: tuple) -> None:
        self._session.udp_datagram_received(data)

    def error_received(self, exc: Exception) -> None:
        log.debug("UDP error: %s", exc)


class UdpTcpRelay:
    """Manages the PC-side TCP server that bridges to the CloudXR runtime's UDP media port."""

    def __init__(
        self,
        tcp_port: int = DEFAULT_RELAY_TCP_PORT,
        udp_host: str = DEFAULT_UDP_TARGET_HOST,
        udp_port: int = DEFAULT_UDP_TARGET_PORT,
    ) -> None:
        self._tcp_port = tcp_port
        self._udp_host = udp_host
        self._udp_port = udp_port
        self._server: asyncio.Server | None = None
        self._current_session: _RelaySession | None = None

    async def start(self) -> None:
        self._server = await asyncio.start_server(
            self._on_connect,
            host="127.0.0.1",
            port=self._tcp_port,
        )
        log.info(
            "UDP-TCP relay listening on TCP :%d -> UDP %s:%d",
            self._tcp_port,
            self._udp_host,
            self._udp_port,
        )

    async def _on_connect(
        self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> None:
        peer = writer.get_extra_info("peername")
        log.info("Relay: new TCP connection from %s", peer)
        if self._current_session is not None:
            log.info("Relay: replacing previous session")
            self._current_session.close()
        session = _RelaySession(
            reader,
            writer,
            self._udp_host,
            self._udp_port,
            asyncio.get_running_loop(),
        )
        self._current_session = session
        try:
            await session.run()
        finally:
            if self._current_session is session:
                self._current_session = None
            log.info("Relay: TCP connection from %s closed", peer)

    async def stop(self) -> None:
        if self._current_session is not None:
            self._current_session.close()
            self._current_session = None
        if self._server is not None:
            self._server.close()
            await self._server.wait_closed()
            self._server = None
        log.info("UDP-TCP relay stopped")
