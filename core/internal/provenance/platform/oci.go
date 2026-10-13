package platform

import (
	"cmp"
	"context"
	"encoding/json"
	"net/http"
	"os"
	"path/filepath"
	"strings"
	"time"
)

var roceCounters = map[string]rdmaCounter{
	"np_ecn_marked_roce_packets": {
		"congestion",
		"packets",
	},
	"rp_cnp_ignored":        {"congestion", "events"},
	"out_of_buffer":         {"discards", "events"},
	"out_of_sequence":       {"discards", "events"},
	"packet_seq_err":        {"discards", "events"},
	"local_ack_timeout_err": {"retransmits", "events"},
	"roce_adp_retrans":      {"retransmits", "events"},
	"roce_adp_retrans_to":   {"retransmits", "events"},
	"roce_slow_restart":     {"retransmits", "events"},
	"rnr_nak_retry_err":     {"retransmits", "events"},
	"implied_nak_seq_err":   {"retransmits", "events"},
	"req_cqe_error":         {"link_errors", "events"},
	"resp_cqe_error": {
		"link_errors",
		"events",
	},
	"req_remote_access_errors": {"link_errors", "events"},
	"resp_local_length_error":  {"link_errors", "events"},
}

type ociAdapter struct {
	collector
	stable *Snapshot
}

func NewOCI(config Config) Adapter {
	return &ociAdapter{
		collector: collector{config: config.normalized(), previous: map[string]float64{}},
	}
}
func (*ociAdapter) Name() string { return "oci" }

func (a *ociAdapter) Collect(ctx context.Context, level int) Snapshot {
	a.mu.Lock()
	defer a.mu.Unlock()
	snapshot := a.collect(ctx, level)
	if a.refreshStable(a.stable) {
		stable := Snapshot{
			Identity:     Identity{Provider: "oci"},
			Topology:     Topology{Levels: []TopologyLevel{}},
			Capabilities: map[string]Capability{},
		}
		base := strings.TrimRight(
			cmp.Or(a.config.MetadataURL, "http://169.254.169.254/opc/v2"),
			"/",
		)
		values := map[string]string{}
		for _, field := range []string{"instance/id", "instance/canonicalRegionName", "instance/availabilityDomain", "instance/faultDomain", "instance/shape", "instance/shapeConfig/gpuDescription", "host/rdmaTopologyData"} {
			requestCtx, cancel := context.WithTimeout(ctx, 500*time.Millisecond)
			request, err := http.NewRequestWithContext(
				requestCtx,
				http.MethodGet,
				base+"/"+field,
				http.NoBody,
			)
			if err != nil {
				cancel()
				stable.Capabilities["metadata"] = Capability{
					Status: "unavailable",
					Reason: "invalid_endpoint",
				}
				break
			}
			request.Header.Set("Authorization", "Bearer Oracle")
			data, capability := a.config.read(request)
			cancel()
			stable.Capabilities["metadata_"+field] = capability
			if capability.Status == "timeout" || capability.Reason == "request_failed" {
				break
			}
			if capability.Status == "available" {
				values[field] = strings.TrimSpace(string(data))
			}
		}
		var rdma struct {
			Island  string `json:"customerHPCIslandId"`
			Network string `json:"customerNetworkBlock"`
			Local   string `json:"customerLocalBlock"`
			Host    string `json:"customerHostId"`
		}
		if raw, ok := values["host/rdmaTopologyData"]; ok &&
			json.Unmarshal([]byte(raw), &rdma) != nil {
			stable.Capabilities["metadata_host/rdmaTopologyData"] = Capability{
				Status: "partial",
				Reason: "invalid_response",
			}
		}
		stable.Identity.InstanceID, _ = a.config.Pseudonym("instance", values["instance/id"])
		stable.Identity.Region = values["instance/canonicalRegionName"]
		stable.Identity.Zone = values["instance/availabilityDomain"]
		stable.Identity.InstanceType = values["instance/shape"]
		stable.Identity.AcceleratorType = values["instance/shapeConfig/gpuDescription"]
		for _, item := range []struct{ role, label, value string }{
			{"fault_domain", "faultDomain", values["instance/faultDomain"]},
			{"hpc_island", "customerHPCIslandId", rdma.Island},
			{"network_block", "customerNetworkBlock", rdma.Network},
			{"local_block", "customerLocalBlock", rdma.Local},
			{"host", "customerHostId", rdma.Host},
		} {
			value, _ := a.config.Pseudonym("topology", item.value)
			stable.Topology.Levels = append(
				stable.Topology.Levels,
				TopologyLevel{Role: item.role, Label: item.label, Value: value},
			)
		}
		a.stable = &stable
	}
	snapshot.Identity = a.stable.Identity
	snapshot.Topology = a.stable.Topology
	for key, value := range a.stable.Capabilities {
		snapshot.Capabilities[key] = value
	}
	ports, capability := a.providerFabric(
		ctx,
		&snapshot,
		"mlx5_*",
		"Ethernet",
		"oci.rocev2.",
		roceCounters,
	)
	snapshot.Capabilities["rocev2"] = capability
	if len(ports) > 0 {
		snapshot.Capabilities["rocev2_ports"] = Capability{Status: "available"}
	}
	for _, port := range ports {
		state, _ := os.ReadFile(filepath.Join(port, "state"))
		physical, _ := os.ReadFile(filepath.Join(port, "phys_state"))
		if !strings.HasSuffix(strings.TrimSpace(string(state)), "ACTIVE") ||
			!strings.HasSuffix(strings.TrimSpace(string(physical)), "LinkUp") {
			snapshot.Capabilities["rocev2_ports"] = Capability{
				Status: "partial",
				Reason: "port_not_active",
			}
		}
	}
	return snapshot
}
