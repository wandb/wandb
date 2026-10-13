package platform

import (
	"context"
	"os"
	"path/filepath"
	"strconv"
	"strings"
)

func (a *collector) fabric(snapshot *Snapshot) {
	paths, _ := filepath.Glob(
		filepath.Join(a.config.SysRoot, "class", "infiniband", "*", "ports", "*"),
	)
	snapshot.Capabilities["rdma"] = Capability{Status: "unavailable", Reason: "devices_not_visible"}
	definitions := map[string]struct {
		family, unit string
		scale        float64
	}{
		"port_xmit_data": {"bytes", "bytes", 4},
		"port_rcv_data":  {"bytes", "bytes", 4},
		"port_xmit_packets": {
			"packets",
			"packets",
			1,
		},
		"port_rcv_packets": {"packets", "packets", 1},
		"port_xmit_wait": {
			"congestion",
			"ticks",
			1,
		},
		"port_xmit_discards": {"discards", "events", 1},
		"port_rcv_errors": {
			"link_errors",
			"events",
			1,
		},
		"symbol_error":   {"link_errors", "events", 1},
		"link_downed":    {"link_errors", "events", 1},
		"rp_cnp_handled": {"congestion", "events", 1},
		"np_cnp_sent": {
			"congestion",
			"events",
			1,
		},
		"rx_icrc_encapsulated": {"link_errors", "events", 1},
		"rx_out_of_buffer":     {"discards", "events", 1},
	}
	for _, port := range paths[:min(len(paths), 64)] {
		snapshot.Capabilities["rdma"] = Capability{Status: "partial", Reason: "namespace_scoped"}
		device := filepath.Base(filepath.Dir(filepath.Dir(port))) + ":" + filepath.Base(port)
		for name, definition := range definitions {
			for _, directory := range []string{"counters", "hw_counters"} {
				data, err := os.ReadFile(filepath.Join(port, directory, name))
				if err != nil {
					continue
				}
				value, err := strconv.ParseUint(strings.TrimSpace(string(data)), 10, 64)
				if err != nil {
					snapshot.Capabilities["rdma"] = Capability{
						Status: "partial",
						Reason: "malformed_counter",
					}
					continue
				}
				number := float64(value) * definition.scale
				snapshot.Counters = append(
					snapshot.Counters,
					Counter{
						Family:    definition.family,
						Name:      "rdma." + name,
						Device:    device,
						Value:     &number,
						Unit:      definition.unit,
						Monotonic: true,
					},
				)
			}
		}
	}
	paths, _ = filepath.Glob(
		filepath.Join(a.config.SysRoot, "bus", "pci", "devices", "*", "aer_dev_*"),
	)
	for _, path := range paths[:min(len(paths), 192)] {
		name := filepath.Base(path)
		if name != "aer_dev_correctable" && name != "aer_dev_nonfatal" && name != "aer_dev_fatal" {
			continue
		}
		data, err := os.ReadFile(path)
		if err != nil {
			continue
		}
		device, ok := a.config.Pseudonym("pci", filepath.Base(filepath.Dir(path)))
		if !ok {
			continue
		}
		for _, line := range strings.Split(string(data), "\n") {
			fields := strings.Fields(line)
			if len(fields) != 2 || !strings.HasPrefix(fields[0], "TOTAL_ERR_") {
				continue
			}
			value, err := strconv.ParseUint(fields[1], 10, 64)
			if err != nil {
				continue
			}
			number := float64(value)
			snapshot.Counters = append(
				snapshot.Counters,
				Counter{
					Family:    "link_errors",
					Name:      "pcie." + name + "." + fields[0],
					Device:    device,
					Value:     &number,
					Unit:      "events",
					Monotonic: true,
				},
			)
		}
	}
}

type rdmaCounter struct{ family, unit string }

// providerFabric maps RDMA devices matching pattern and adds their hw_counters under prefix; it returns the visited port paths.
func (a *collector) providerFabric(
	ctx context.Context,
	snapshot *Snapshot,
	pattern, linkLayer, prefix string,
	definitions map[string]rdmaCounter,
) ([]string, Capability) {
	paths, _ := filepath.Glob(
		filepath.Join(a.config.SysRoot, "class", "infiniband", pattern, "ports", "*"),
	)
	capability := Capability{Status: "unavailable", Reason: "devices_not_visible"}
	mapped := map[string]bool{}
	ports := []string{}
	for _, port := range paths[:min(len(paths), 64)] {
		if ctx.Err() != nil {
			return ports, Capability{Status: "timeout", Reason: "collection_timeout"}
		}
		if linkLayer != "" {
			if data, err := os.ReadFile(
				filepath.Join(port, "link_layer"),
			); err != nil ||
				strings.TrimSpace(string(data)) != linkLayer {
				continue
			}
		}
		ports = append(ports, port)
		root := filepath.Dir(filepath.Dir(port))
		name := filepath.Base(root)
		if !mapped[name] {
			mapped[name] = true
			entry := NetworkDevice{Name: name}
			if data, err := os.ReadFile(filepath.Join(root, "device", "numa_node")); err == nil {
				if node, err := strconv.Atoi(
					strings.TrimSpace(string(data)),
				); err == nil &&
					node >= 0 {
					entry.NUMA = &node
				}
			}
			if path, err := filepath.EvalSymlinks(filepath.Join(root, "device")); err == nil {
				entry.PCIID, _ = a.config.Pseudonym("pci", filepath.Base(path))
			}
			snapshot.Networks = append(snapshot.Networks, entry)
		}
		if capability.Status == "unavailable" {
			capability = Capability{Status: "available"}
		}
		device := name + ":" + filepath.Base(port)
		for counter, definition := range definitions {
			data, err := os.ReadFile(filepath.Join(port, "hw_counters", counter))
			if err != nil {
				continue
			}
			value, err := strconv.ParseUint(strings.TrimSpace(string(data)), 10, 64)
			if err != nil {
				capability = Capability{Status: "partial", Reason: "malformed_counter"}
				continue
			}
			number := float64(value)
			snapshot.Counters = append(
				snapshot.Counters,
				Counter{
					Family:    definition.family,
					Name:      prefix + counter,
					Device:    device,
					Value:     &number,
					Unit:      definition.unit,
					Monotonic: true,
				},
			)
		}
	}
	return ports, capability
}
