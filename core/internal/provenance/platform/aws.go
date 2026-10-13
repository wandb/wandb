package platform

import (
	"cmp"
	"context"
	"net/http"
	"strings"
	"time"
)

var efaCounters = map[string]rdmaCounter{
	"tx_bytes":              {"bytes", "bytes"},
	"rx_bytes":              {"bytes", "bytes"},
	"send_bytes":            {"bytes", "bytes"},
	"recv_bytes":            {"bytes", "bytes"},
	"rdma_read_bytes":       {"bytes", "bytes"},
	"rdma_write_bytes":      {"bytes", "bytes"},
	"rdma_read_resp_bytes":  {"bytes", "bytes"},
	"rdma_write_recv_bytes": {"bytes", "bytes"},
	"tx_pkts":               {"packets", "packets"},
	"rx_pkts":               {"packets", "packets"},
	"send_wrs":              {"rdma_operations", "operations"},
	"recv_wrs":              {"rdma_operations", "operations"},
	"rdma_read_wrs": {
		"rdma_operations",
		"operations",
	},
	"rdma_write_wrs":         {"rdma_operations", "operations"},
	"retrans_bytes":          {"retransmits", "bytes"},
	"retrans_pkts":           {"retransmits", "packets"},
	"retrans_timeout_events": {"retransmits", "events"},
	"rx_drops":               {"discards", "packets"},
	"rdma_read_wr_err":       {"link_errors", "events"},
	"rdma_write_wr_err":      {"link_errors", "events"},
	"unresponsive_remote_events": {
		"link_errors",
		"events",
	},
	"impaired_remote_conn_events": {"link_errors", "events"},
}

type awsAdapter struct {
	collector
	stable *Snapshot
}

func NewAWS(config Config) Adapter {
	return &awsAdapter{
		collector: collector{config: config.normalized(), previous: map[string]float64{}},
	}
}
func (*awsAdapter) Name() string { return "aws" }

func (a *awsAdapter) Collect(ctx context.Context, level int) Snapshot {
	a.mu.Lock()
	defer a.mu.Unlock()
	snapshot := a.collect(ctx, level)
	if a.refreshStable(a.stable) {
		stable := Snapshot{
			Identity:     Identity{Provider: "aws"},
			Topology:     Topology{Levels: []TopologyLevel{}},
			Capabilities: map[string]Capability{},
		}
		base := strings.TrimRight(cmp.Or(a.config.MetadataURL, "http://169.254.169.254"), "/")
		values := map[string]string{}
		requestCtx, cancel := context.WithTimeout(ctx, 500*time.Millisecond)
		request, err := http.NewRequestWithContext(
			requestCtx,
			http.MethodPut,
			base+"/latest/api/token",
			http.NoBody,
		)
		if err != nil {
			stable.Capabilities["metadata"] = Capability{
				Status: "unavailable",
				Reason: "invalid_endpoint",
			}
		} else {
			request.Header.Set("X-aws-ec2-metadata-token-ttl-seconds", "60")
			token, capability := a.config.read(request)
			stable.Capabilities["metadata_token"] = capability
			for _, field := range []string{"instance-id", "instance-type", "placement/region", "placement/availability-zone", "placement/group-name"} {
				if capability.Status != "available" {
					break
				}
				fieldCtx, fieldCancel := context.WithTimeout(ctx, 500*time.Millisecond)
				request, err = http.NewRequestWithContext(
					fieldCtx,
					http.MethodGet,
					base+"/latest/meta-data/"+field,
					http.NoBody,
				)
				if err != nil {
					fieldCancel()
					break
				}
				request.Header.Set("X-aws-ec2-metadata-token", strings.TrimSpace(string(token)))
				data, fieldCapability := a.config.read(request)
				fieldCancel()
				stable.Capabilities["metadata_"+field] = fieldCapability
				if fieldCapability.Status == "available" {
					values[field] = strings.TrimSpace(string(data))
				}
			}
		}
		cancel()
		stable.Identity.InstanceID, _ = a.config.Pseudonym("instance", values["instance-id"])
		stable.Identity.InstanceType = values["instance-type"]
		stable.Identity.Region = values["placement/region"]
		stable.Identity.Zone = values["placement/availability-zone"]
		labels, capability := a.config.nodeLabels(ctx)
		stable.Capabilities["kubernetes"] = capability
		for _, item := range []struct{ role, label, value string }{
			{"placement_group", "placement/group-name", values["placement/group-name"]},
			{"network_node_layer_1", "topology.k8s.aws/network-node-layer-1", labels["topology.k8s.aws/network-node-layer-1"]},
			{"network_node_layer_2", "topology.k8s.aws/network-node-layer-2", labels["topology.k8s.aws/network-node-layer-2"]},
			{"network_node_layer_3", "topology.k8s.aws/network-node-layer-3", labels["topology.k8s.aws/network-node-layer-3"]},
			{"host", "instance-id", values["instance-id"]},
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
	_, snapshot.Capabilities["efa"] = a.providerFabric(
		ctx,
		&snapshot,
		"rdmap*",
		"",
		"aws.efa.",
		efaCounters,
	)
	return snapshot
}
