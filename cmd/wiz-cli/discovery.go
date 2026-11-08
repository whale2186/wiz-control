package main

import (
	"bufio"
	"encoding/json"
	"net"
	"os"
	"strings"
	"sync"
	"time"
)

type DiscoveredBulb struct {
	IP         string
	Mac        string
	ModuleName string
}

// DiscoverBulbs broadcasts and probes the local network for WiZ lights.
// If onFound is non-nil, it is called as soon as any bulb responds, without waiting
// for the entire timeout to finish.
func DiscoverBulbs(listenTimeout time.Duration, onFound func(DiscoveredBulb)) []DiscoveredBulb {
	if listenTimeout <= 0 {
		listenTimeout = 1200 * time.Millisecond
	}

	packetConn, err := newPacketConn()
	if err != nil {
		return nil
	}
	defer packetConn.Close()

	req := []byte(`{"method":"getSystemConfig","params":{}}`)

	// 1. Send broadcast to general broadcast address
	bcastAny, _ := net.ResolveUDPAddr("udp4", "255.255.255.255:38899")
	if bcastAny != nil {
		packetConn.WriteTo(req, bcastAny)
	}

	// 2. Discover local LAN subnets and broadcast to each
	var subnets []net.IPNet
	if ifaces, err := net.Interfaces(); err == nil {
		for _, iface := range ifaces {
			if iface.Flags&net.FlagUp == 0 || iface.Flags&net.FlagLoopback != 0 {
				continue
			}
			name := strings.ToLower(iface.Name)
			if strings.HasPrefix(name, "docker") || strings.HasPrefix(name, "veth") || strings.HasPrefix(name, "tailscale") {
				continue
			}

			addrs, err := iface.Addrs()
			if err != nil {
				continue
			}
			for _, addr := range addrs {
				ipNet, ok := addr.(*net.IPNet)
				if !ok || ipNet.IP.To4() == nil {
					continue
				}
				ip4 := ipNet.IP.To4()
				mask := ipNet.Mask
				if len(mask) == 4 {
					bcastIP := net.IPv4(
						ip4[0]|^mask[0],
						ip4[1]|^mask[1],
						ip4[2]|^mask[2],
						ip4[3]|^mask[3],
					)
					target, _ := net.ResolveUDPAddr("udp4", net.JoinHostPort(bcastIP.String(), "38899"))
					if target != nil {
						packetConn.WriteTo(req, target)
					}
					subnets = append(subnets, *ipNet)
				}
			}
		}
	}

	// 3. Probe active ARP entries from /proc/net/arp immediately (zero latency)
	if f, err := os.Open("/proc/net/arp"); err == nil {
		scanner := bufio.NewScanner(f)
		for scanner.Scan() {
			fields := strings.Fields(scanner.Text())
			if len(fields) >= 4 && fields[2] == "0x2" { // 0x2 = completed ARP entry
				ip := fields[0]
				if parsed := net.ParseIP(ip); parsed != nil && parsed.To4() != nil {
					target, _ := net.ResolveUDPAddr("udp4", net.JoinHostPort(ip, "38899"))
					if target != nil {
						packetConn.WriteTo(req, target)
					}
				}
			}
		}
		f.Close()
	}

	// 4. Sweep subnet IPs concurrently
	doneSweep := make(chan struct{})
	go func() {
		defer close(doneSweep)
		var wg sync.WaitGroup
		sem := make(chan struct{}, 40)

		for _, subnet := range subnets {
			ip4 := subnet.IP.To4()
			if ip4 == nil {
				continue
			}
			for host := 1; host <= 254; host++ {
				wg.Add(1)
				sem <- struct{}{}
				go func(b0, b1, b2, b3 byte) {
					defer wg.Done()
					defer func() { <-sem }()
					target, _ := net.ResolveUDPAddr("udp4", net.JoinHostPort(net.IPv4(b0, b1, b2, b3).String(), "38899"))
					if target != nil {
						packetConn.WriteTo(req, target)
					}
				}(ip4[0], ip4[1], ip4[2], byte(host))
			}
		}
		wg.Wait()
	}()

	packetConn.SetReadDeadline(time.Now().Add(listenTimeout))
	buf := make([]byte, 2048)

	seen := make(map[string]bool)
	var discovered []DiscoveredBulb
	var discMu sync.Mutex

	for {
		n, addr, err := packetConn.ReadFrom(buf)
		if err != nil {
			break
		}
		udpAddr, ok := addr.(*net.UDPAddr)
		if !ok {
			continue
		}
		ip := udpAddr.IP.String()

		discMu.Lock()
		alreadySeen := seen[ip]
		if !alreadySeen {
			seen[ip] = true
		}
		discMu.Unlock()

		if alreadySeen {
			continue
		}

		var resp struct {
			Result struct {
				Mac        string `json:"mac"`
				ModuleName string `json:"moduleName"`
			} `json:"result"`
		}
		if err := json.Unmarshal(buf[:n], &resp); err == nil && resp.Result.Mac != "" {
			mod := resp.Result.ModuleName
			if mod == "" {
				mod = "WiZ Light"
			}
			bulb := DiscoveredBulb{
				IP:         ip,
				Mac:        resp.Result.Mac,
				ModuleName: mod,
			}
			discMu.Lock()
			discovered = append(discovered, bulb)
			discMu.Unlock()

			if onFound != nil {
				onFound(bulb)
			}
		}
	}

	<-doneSweep
	return discovered
}
