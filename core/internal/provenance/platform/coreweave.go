package platform

import "context"

type coreweaveAdapter struct {
	collector
	stable *Snapshot
}

func NewCoreWeave(config Config) Adapter {
	return &coreweaveAdapter{
		collector: collector{config: config.normalized(), previous: map[string]float64{}},
	}
}
func (*coreweaveAdapter) Name() string { return "coreweave" }

func (a *coreweaveAdapter) Collect(ctx context.Context, level int) Snapshot {
	a.mu.Lock()
	defer a.mu.Unlock()
	snapshot := a.collect(ctx, level)
	if a.refreshStable(a.stable) {
		labels, capability := a.config.nodeLabels(ctx)
		stable := Snapshot{
			Identity:     Identity{Provider: "coreweave", Region: a.config.Env["COREWEAVE_REGION"]},
			Topology:     Topology{Levels: []TopologyLevel{}},
			Capabilities: map[string]Capability{"kubernetes": capability},
		}
		stable.Identity.InstanceType = labels["node.kubernetes.io/instance-type"]
		stable.Identity.AcceleratorType = labels["gpu.nvidia.com/model"]
		stable.Identity.Zone = labels["topology.kubernetes.io/zone"]
		if stable.Identity.Region == "" {
			stable.Identity.Region = labels["topology.kubernetes.io/region"]
		}
		for _, item := range []struct{ role, label string }{{"fabric", "ib.coreweave.cloud/fabric"}, {"leaf", "ib.coreweave.cloud/leafgroup"}, {"host", "kubernetes.io/hostname"}} {
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
	if level == 1 {
		snapshot.Capabilities["mission_control"] = Capability{
			Status: "unavailable",
			Reason: "missing_credentials",
		}
	}
	return snapshot
}
