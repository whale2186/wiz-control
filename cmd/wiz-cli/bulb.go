package main

import (
	"encoding/json"
	"fmt"
	"net"
	"sync"
	"time"
)

const (
	DefaultWizPort = 38899
	MinDebounceMs  = 65
)

type BulbState struct {
	MAC         string `json:"mac"`
	RSSI        int    `json:"rssi"`
	State       bool   `json:"state"`
	SceneID     int    `json:"sceneId"`
	Speed       int    `json:"speed"`
	R           int    `json:"r"`
	G           int    `json:"g"`
	B           int    `json:"b"`
	Dimming     int    `json:"dimming"`
	Temperature int    `json:"temp"`
}

type BulbClient struct {
	IP   string
	Port int

	netMu       sync.Mutex
	mu          sync.Mutex
	lastSent    time.Time
	pendingReq  map[string]interface{}
	debounceTmr *time.Timer
}

func NewBulbClient(ip string) *BulbClient {
	return &BulbClient{
		IP:   ip,
		Port: DefaultWizPort,
	}
}

func (c *BulbClient) sendCommand(method string, params map[string]interface{}, timeout time.Duration) ([]byte, error) {
	c.netMu.Lock()
	defer c.netMu.Unlock()

	addr, err := net.ResolveUDPAddr("udp", fmt.Sprintf("%s:%d", c.IP, c.Port))
	if err != nil {
		return nil, fmt.Errorf("resolve UDP addr: %w", err)
	}

	conn, err := net.DialUDP("udp", nil, addr)
	if err != nil {
		return nil, fmt.Errorf("dial UDP: %w", err)
	}
	defer conn.Close()

	if timeout > 0 {
		conn.SetDeadline(time.Now().Add(timeout))
	}

	req := map[string]interface{}{
		"method": method,
		"params": params,
	}
	payload, err := json.Marshal(req)
	if err != nil {
		return nil, fmt.Errorf("marshal JSON: %w", err)
	}

	if _, err := conn.Write(payload); err != nil {
		return nil, fmt.Errorf("write UDP: %w", err)
	}

	if timeout > 0 {
		buf := make([]byte, 2048)
		n, err := conn.Read(buf)
		if err != nil {
			return nil, fmt.Errorf("read UDP: %w", err)
		}
		return buf[:n], nil
	}

	return nil, nil
}

func (c *BulbClient) GetState() (*BulbState, error) {
	var respBytes []byte
	var err error

	// Retry once if first attempt dropped over WiFi
	for attempt := 0; attempt < 2; attempt++ {
		respBytes, err = c.sendCommand("getPilot", map[string]interface{}{}, 1200*time.Millisecond)
		if err == nil {
			break
		}
		time.Sleep(80 * time.Millisecond)
	}
	if err != nil {
		return nil, err
	}

	var parsed struct {
		Result BulbState `json:"result"`
	}
	if err := json.Unmarshal(respBytes, &parsed); err != nil {
		return nil, fmt.Errorf("parse bulb response: %w", err)
	}

	return &parsed.Result, nil
}

func (c *BulbClient) SetPilotImmediate(params map[string]interface{}) error {
	c.mu.Lock()
	c.lastSent = time.Now()
	c.pendingReq = nil
	if c.debounceTmr != nil {
		c.debounceTmr.Stop()
	}
	c.mu.Unlock()

	_, err := c.sendCommand("setPilot", params, 0)
	return err
}

func (c *BulbClient) SetPilotDebounced(params map[string]interface{}) {
	c.mu.Lock()
	defer c.mu.Unlock()

	c.pendingReq = params
	now := time.Now()
	elapsed := now.Sub(c.lastSent)

	if elapsed >= MinDebounceMs*time.Millisecond {
		c.lastSent = now
		req := c.pendingReq
		c.pendingReq = nil
		go c.sendCommand("setPilot", req, 0)
		return
	}

	if c.debounceTmr != nil {
		c.debounceTmr.Stop()
	}

	remaining := (MinDebounceMs * time.Millisecond) - elapsed
	c.debounceTmr = time.AfterFunc(remaining, func() {
		c.mu.Lock()
		req := c.pendingReq
		c.pendingReq = nil
		c.lastSent = time.Now()
		c.mu.Unlock()

		if req != nil {
			c.sendCommand("setPilot", req, 0)
		}
	})
}

func (c *BulbClient) SetPower(on bool) error {
	return c.SetPilotImmediate(map[string]interface{}{
		"state": on,
	})
}

func (c *BulbClient) SetBrightness(dimming int) {
	if dimming < 10 {
		dimming = 10
	} else if dimming > 100 {
		dimming = 100
	}
	c.SetPilotDebounced(map[string]interface{}{
		"state":   true,
		"dimming": dimming,
	})
}

func (c *BulbClient) SetColor(r, g, b int, dimming int) {
	params := map[string]interface{}{
		"state": true,
		"r":     r,
		"g":     g,
		"b":     b,
	}
	if dimming >= 10 {
		params["dimming"] = dimming
	}
	c.SetPilotDebounced(params)
}

func (c *BulbClient) SetTemperature(tempKelvin int, dimming int) {
	if tempKelvin < 2200 {
		tempKelvin = 2200
	} else if tempKelvin > 6500 {
		tempKelvin = 6500
	}
	params := map[string]interface{}{
		"state": true,
		"temp":  tempKelvin,
	}
	if dimming >= 10 {
		params["dimming"] = dimming
	}
	c.SetPilotDebounced(params)
}

func (c *BulbClient) SetScene(sceneID int, speed int) error {
	return c.SetPilotImmediate(map[string]interface{}{
		"state":   true,
		"sceneId": sceneID,
		"speed":   speed,
	})
}
