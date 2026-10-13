package platform

import (
	"bufio"
	"context"
	"io"
	"os"
	"os/exec"
	"path/filepath"
	"strconv"
	"strings"
	"time"
)

func (a *collector) network(ctx context.Context, level int, snapshot *Snapshot) {
	devices, err := os.ReadDir(filepath.Join(a.config.SysRoot, "class", "net"))
	if err != nil {
		snapshot.Capabilities["network"] = Capability{
			Status: "unavailable",
			Reason: "sysfs_unavailable",
		}
		return
	}
	snapshot.Capabilities["network"] = Capability{Status: "partial", Reason: "namespace_scoped"}
	counters := map[string]string{
		"tx_bytes":   "bytes",
		"rx_bytes":   "bytes",
		"tx_packets": "packets",
		"rx_packets": "packets",
		"tx_dropped": "discards",
		"rx_dropped": "discards",
		"tx_errors":  "link_errors",
		"rx_errors":  "link_errors",
	}
	for _, device := range devices[:min(len(devices), 64)] {
		if ctx.Err() != nil {
			snapshot.Capabilities["network"] = Capability{
				Status: "timeout",
				Reason: "collection_timeout",
			}
			return
		}
		name := device.Name()
		if name == "lo" {
			continue
		}
		entry := NetworkDevice{Name: name}
		if data, err := os.ReadFile(
			filepath.Join(a.config.SysRoot, "class", "net", name, "device", "numa_node"),
		); err == nil {
			if node, err := strconv.Atoi(strings.TrimSpace(string(data))); err == nil && node >= 0 {
				entry.NUMA = &node
			}
		}
		if path, err := filepath.EvalSymlinks(
			filepath.Join(a.config.SysRoot, "class", "net", name, "device"),
		); err == nil {
			entry.PCIID, _ = a.config.Pseudonym("pci", filepath.Base(path))
		}
		snapshot.Networks = append(snapshot.Networks, entry)
		for counter, family := range counters {
			data, err := os.ReadFile(
				filepath.Join(a.config.SysRoot, "class", "net", name, "statistics", counter),
			)
			if err != nil {
				continue
			}
			value, err := strconv.ParseUint(strings.TrimSpace(string(data)), 10, 64)
			if err != nil {
				snapshot.Capabilities["network"] = Capability{
					Status: "partial",
					Reason: "malformed_counter",
				}
				continue
			}
			unit := map[string]string{"bytes": "bytes", "packets": "packets"}[family]
			if unit == "" {
				unit = "events"
			}
			number := float64(value)
			snapshot.Counters = append(
				snapshot.Counters,
				Counter{
					Family:    family,
					Name:      counter,
					Device:    name,
					Value:     &number,
					Unit:      unit,
					Monotonic: true,
				},
			)
		}
		if level != 1 {
			continue
		}
		a.driverCounters(ctx, name, snapshot)
	}
}

// driverCounters adds Level 1 ethtool -S discard and error counters for device.
func (a *collector) driverCounters(ctx context.Context, device string, snapshot *Snapshot) {
	commandCtx, cancel := context.WithTimeout(ctx, 500*time.Millisecond)
	command := exec.CommandContext(commandCtx, "ethtool", "-S", device)
	pipe, err := command.StdoutPipe()
	if err != nil {
		cancel()
		return
	}
	if err = command.Start(); err != nil {
		cancel()
		snapshot.Capabilities["driver_counters"] = Capability{
			Status: "unavailable",
			Reason: "ethtool_unavailable",
		}
		return
	}
	data, readErr := io.ReadAll(io.LimitReader(pipe, 64<<10))
	pipe.Close()
	waitErr := command.Wait()
	cancel()
	if readErr != nil || waitErr != nil || len(data) == 64<<10 {
		snapshot.Capabilities["driver_counters"] = Capability{
			Status: "partial",
			Reason: "ethtool_unavailable",
		}
		return
	}
	scanner := bufio.NewScanner(strings.NewReader(string(data)))
	for scanner.Scan() {
		key, raw, ok := strings.Cut(strings.TrimSpace(scanner.Text()), ":")
		if !ok {
			continue
		}
		family := map[string]string{"rx_dropped": "discards", "tx_dropped": "discards", "rx_errors": "link_errors", "tx_errors": "link_errors", "rx_crc_errors": "link_errors", "rx_missed_errors": "discards"}[key]
		if family == "" {
			continue
		}
		value, err := strconv.ParseUint(strings.TrimSpace(raw), 10, 64)
		if err != nil {
			continue
		}
		number := float64(value)
		snapshot.Counters = append(
			snapshot.Counters,
			Counter{
				Family:    family,
				Name:      "ethtool." + key,
				Device:    device,
				Value:     &number,
				Unit:      "events",
				Monotonic: true,
			},
		)
	}
	snapshot.Capabilities["driver_counters"] = Capability{Status: "available"}
}
