package platform

import (
	"cmp"
	"context"
	"net/http"
	"path"
	"strings"
	"time"
)

type gcpAdapter struct {
	collector
	stable *Snapshot
}

func NewGCP(config Config) Adapter {
	return &gcpAdapter{
		collector: collector{config: config.normalized(), previous: map[string]float64{}},
	}
}
func (*gcpAdapter) Name() string { return "gcp" }

func (a *gcpAdapter) Collect(ctx context.Context, level int) Snapshot {
	a.mu.Lock()
	defer a.mu.Unlock()
	snapshot := a.collect(ctx, level)
	if a.refreshStable(a.stable) {
		stable := Snapshot{
			Identity:     Identity{Provider: "gcp"},
			Topology:     Topology{Levels: []TopologyLevel{}},
			Capabilities: map[string]Capability{},
		}
		base := cmp.Or(a.config.MetadataURL, "http://metadata.google.internal/computeMetadata/v1")
		for _, field := range []string{"id", "zone", "machine-type", "attributes/accelerator-type"} {
			requestCtx, cancel := context.WithTimeout(ctx, 500*time.Millisecond)
			request, err := http.NewRequestWithContext(
				requestCtx,
				http.MethodGet,
				strings.TrimRight(base, "/")+"/instance/"+field,
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
			request.Header.Set("Metadata-Flavor", "Google")
			data, capability := a.config.read(request)
			cancel()
			if capability.Status != "available" {
				stable.Capabilities["metadata_"+field] = capability
				continue
			}
			value := strings.TrimSpace(string(data))
			switch field {
			case "id":
				stable.Identity.InstanceID, _ = a.config.Pseudonym("instance", value)
			case "zone":
				stable.Identity.Zone = path.Base(value)
				stable.Identity.Region = stable.Identity.Zone[:max(0, strings.LastIndex(stable.Identity.Zone, "-"))]
			case "machine-type":
				stable.Identity.InstanceType = path.Base(value)
			case "attributes/accelerator-type":
				stable.Identity.AcceleratorType = path.Base(value)
			}
			stable.Capabilities["metadata_"+field] = capability
		}
		labels, capability := a.config.nodeLabels(ctx)
		stable.Capabilities["kubernetes"] = capability
		for _, item := range []struct{ role, label string }{{"block", "cloud.google.com/gce-topology-block"}, {"subblock", "cloud.google.com/gce-topology-subblock"}, {"host", "cloud.google.com/gce-topology-host"}} {
			value, _ := a.config.Pseudonym("topology", labels[item.label])
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
	return snapshot
}
