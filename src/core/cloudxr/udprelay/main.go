// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

// udprelay is the headset-side component of the UDP-over-TCP tunnel for adb reverse.
//
// It listens for UDP datagrams on a local port (default 47998, the CloudXR media port)
// and tunnels them over a TCP connection to the PC-side relay (default TCP 47999,
// reached via adb reverse). The PC relay then forwards each datagram as real UDP to
// the CloudXR runtime.
//
// Framing: each datagram is prefixed with a 2-byte big-endian uint16 length header.
// Both directions use the same framing on the single TCP connection.
//
// Build for Android headset:
//
//	GOOS=linux GOARCH=arm64 go build -o udprelay .
package main

import (
	"encoding/binary"
	"flag"
	"fmt"
	"io"
	"log"
	"net"
	"os"
	"os/signal"
	"sync"
	"syscall"
)

func main() {
	udpPort := flag.Int("udp-port", 47998, "Local UDP listen port (CloudXR media)")
	tcpPort := flag.Int("tcp-port", 47999, "TCP port to connect to (adb-reversed to PC relay)")
	tcpHost := flag.String("tcp-host", "127.0.0.1", "TCP host to connect to")
	flag.Parse()

	udpAddr, err := net.ResolveUDPAddr("udp", fmt.Sprintf("0.0.0.0:%d", *udpPort))
	if err != nil {
		log.Fatalf("resolve UDP addr: %v", err)
	}

	udpConn, err := net.ListenUDP("udp", udpAddr)
	if err != nil {
		log.Fatalf("listen UDP :%d: %v", *udpPort, err)
	}
	defer udpConn.Close()
	log.Printf("Listening UDP on :%d", *udpPort)

	tcpTarget := fmt.Sprintf("%s:%d", *tcpHost, *tcpPort)
	tcpConn, err := net.Dial("tcp", tcpTarget)
	if err != nil {
		log.Fatalf("connect TCP %s: %v", tcpTarget, err)
	}
	defer tcpConn.Close()
	log.Printf("Connected TCP to %s", tcpTarget)

	sigCh := make(chan os.Signal, 1)
	signal.Notify(sigCh, syscall.SIGINT, syscall.SIGTERM)

	var (
		mu         sync.Mutex
		clientAddr *net.UDPAddr // last-seen UDP peer (the WebRTC client)
	)

	// UDP → TCP: read UDP datagrams, length-prefix, send on TCP.
	go func() {
		buf := make([]byte, 65535+2)
		for {
			n, addr, err := udpConn.ReadFromUDP(buf[2:])
			if err != nil {
				log.Printf("UDP read error: %v", err)
				return
			}
			mu.Lock()
			clientAddr = addr
			mu.Unlock()

			binary.BigEndian.PutUint16(buf[:2], uint16(n))
			if _, err := tcpConn.Write(buf[:2+n]); err != nil {
				log.Printf("TCP write error: %v", err)
				return
			}
		}
	}()

	// TCP → UDP: read length-prefixed frames, send as UDP back to last-seen client.
	go func() {
		hdr := make([]byte, 2)
		payload := make([]byte, 65535)
		for {
			if _, err := io.ReadFull(tcpConn, hdr); err != nil {
				if err != io.EOF {
					log.Printf("TCP read header error: %v", err)
				}
				return
			}
			length := binary.BigEndian.Uint16(hdr)
			if length == 0 {
				continue
			}
			if _, err := io.ReadFull(tcpConn, payload[:length]); err != nil {
				log.Printf("TCP read payload error: %v", err)
				return
			}

			mu.Lock()
			dst := clientAddr
			mu.Unlock()
			if dst == nil {
				continue
			}
			if _, err := udpConn.WriteToUDP(payload[:length], dst); err != nil {
				log.Printf("UDP write error: %v", err)
			}
		}
	}()

	sig := <-sigCh
	log.Printf("Received %v, shutting down", sig)
	os.Exit(0)
}
