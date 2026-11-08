//go:build !windows

package main

import (
	"net"
	"syscall"
)

func newPacketConn() (net.PacketConn, error) {
	lc := net.ListenConfig{
		Control: func(network, address string, c syscall.RawConn) error {
			return c.Control(func(fd uintptr) {
				syscall.SetsockoptInt(int(fd), syscall.SOL_SOCKET, syscall.SO_BROADCAST, 1)
			})
		},
	}
	conn, err := lc.ListenPacket(nil, "udp4", ":0")
	if err == nil {
		return conn, nil
	}
	return net.ListenPacket("udp4", ":0")
}
