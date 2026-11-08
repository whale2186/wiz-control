package main

import (
	"encoding/json"
	"flag"
	"fmt"
	"os"
	"strconv"
	"strings"
	"time"
)

func printUsage() {
	fmt.Println(`WiZ Light Control CLI

Usage:
  wiz-cli scan                      Scan local network for WiZ lights
  wiz-cli status <ip>               Get current state of bulb
  wiz-cli on <ip>                   Turn light on
  wiz-cli off <ip>                  Turn light off
  wiz-cli dim <ip> <10-100>         Set brightness percentage
  wiz-cli color <ip> <r> <g> <b>    Set RGB color (0-255)
  wiz-cli temp <ip> <2200-6500>     Set white color temperature (Kelvin)
  wiz-cli scene <ip> <scene-id>     Activate scene (1-32)

Scenes:
  1: Ocean        2: Sunset       3: Party        4: Fireplace
  5: Cozy         6: Forest       7: Pastel       8: Wake up
  9: Bedtime     10: Warm White  11: Daylight    12: Night light
 13: Focus       14: Relax       15: True colors 16: TV time
 17: Plantgrowth 18: Spring      19: Summer      20: Fall
 21: Deepdive    22: Jungle      23: Mojave      24: Club
 25: Christmas   26: Halloween   27: Candlelight 28: Golden white
 29: Pulse       30: Steampunk   31: Diwali      32: Rhythm
`)
}

func main() {
	flag.Parse()
	args := flag.Args()

	if len(args) == 0 {
		printUsage()
		return
	}

	cmd := strings.ToLower(args[0])

	switch cmd {
	case "scan", "discover":
		fmt.Println("Scanning local network for WiZ lights...")
		bulbs := DiscoverBulbs(1500*time.Millisecond, func(b DiscoveredBulb) {
			fmt.Printf(" [Found] %s\tMAC: %s\tModel: %s\n", b.IP, b.Mac, b.ModuleName)
		})
		fmt.Printf("\nScan complete. Total lights found: %d\n", len(bulbs))

	case "status", "get":
		if len(args) < 2 {
			fmt.Println("Usage: wiz-cli status <ip>")
			os.Exit(1)
		}
		ip := args[1]
		client := NewBulbClient(ip)
		state, err := client.GetState()
		if err != nil {
			fmt.Fprintf(os.Stderr, "Error getting status from %s: %v\n", ip, err)
			os.Exit(1)
		}
		out, _ := json.MarshalIndent(state, "", "  ")
		fmt.Println(string(out))

	case "on":
		if len(args) < 2 {
			fmt.Println("Usage: wiz-cli on <ip>")
			os.Exit(1)
		}
		ip := args[1]
		client := NewBulbClient(ip)
		if err := client.SetPower(true); err != nil {
			fmt.Fprintf(os.Stderr, "Error turning on %s: %v\n", ip, err)
			os.Exit(1)
		}
		fmt.Printf("Turned ON %s\n", ip)

	case "off":
		if len(args) < 2 {
			fmt.Println("Usage: wiz-cli off <ip>")
			os.Exit(1)
		}
		ip := args[1]
		client := NewBulbClient(ip)
		if err := client.SetPower(false); err != nil {
			fmt.Fprintf(os.Stderr, "Error turning off %s: %v\n", ip, err)
			os.Exit(1)
		}
		fmt.Printf("Turned OFF %s\n", ip)

	case "dim", "brightness":
		if len(args) < 3 {
			fmt.Println("Usage: wiz-cli dim <ip> <10-100>")
			os.Exit(1)
		}
		ip := args[1]
		val, err := strconv.Atoi(args[2])
		if err != nil || val < 10 || val > 100 {
			fmt.Fprintln(os.Stderr, "Brightness must be an integer between 10 and 100")
			os.Exit(1)
		}
		client := NewBulbClient(ip)
		client.SetBrightness(val)
		fmt.Printf("Set brightness of %s to %d%%\n", ip, val)

	case "color", "rgb":
		if len(args) < 5 {
			fmt.Println("Usage: wiz-cli color <ip> <r> <g> <b>")
			os.Exit(1)
		}
		ip := args[1]
		r, err1 := strconv.Atoi(args[2])
		g, err2 := strconv.Atoi(args[3])
		b, err3 := strconv.Atoi(args[4])
		if err1 != nil || err2 != nil || err3 != nil || r < 0 || r > 255 || g < 0 || g > 255 || b < 0 || b > 255 {
			fmt.Fprintln(os.Stderr, "R, G, and B must be integers between 0 and 255")
			os.Exit(1)
		}
		client := NewBulbClient(ip)
		client.SetColor(r, g, b, 100)
		fmt.Printf("Set color of %s to RGB(%d, %d, %d)\n", ip, r, g, b)

	case "temp", "kelvin":
		if len(args) < 3 {
			fmt.Println("Usage: wiz-cli temp <ip> <2200-6500>")
			os.Exit(1)
		}
		ip := args[1]
		kelvin, err := strconv.Atoi(args[2])
		if err != nil || kelvin < 2200 || kelvin > 6500 {
			fmt.Fprintln(os.Stderr, "Color temperature must be between 2200 and 6500 Kelvin")
			os.Exit(1)
		}
		client := NewBulbClient(ip)
		client.SetTemperature(kelvin, 100)
		fmt.Printf("Set temperature of %s to %d K\n", ip, kelvin)

	case "scene":
		if len(args) < 3 {
			fmt.Println("Usage: wiz-cli scene <ip> <scene-id>")
			os.Exit(1)
		}
		ip := args[1]
		sceneID, err := strconv.Atoi(args[2])
		if err != nil || sceneID < 1 || sceneID > 32 {
			fmt.Fprintln(os.Stderr, "Scene ID must be between 1 and 32")
			os.Exit(1)
		}
		client := NewBulbClient(ip)
		client.SetScene(sceneID, 100)
		fmt.Printf("Activated scene %d on %s\n", sceneID, ip)

	case "-h", "--help", "help":
		printUsage()

	default:
		fmt.Printf("Unknown command: %s\n\n", cmd)
		printUsage()
		os.Exit(1)
	}
}
