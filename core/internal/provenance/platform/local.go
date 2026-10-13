package platform

import (
	"context"
	"sync"
)

type collector struct {
	config   Config
	previous map[string]float64
	mu       sync.Mutex
	collects int
}

// refreshStable reports whether stable identity should be read again, backing off exponentially after transient failures.
func (c *collector) refreshStable(stable *Snapshot) bool {
	c.collects++
	if stable == nil {
		return true
	}
	if c.collects&(c.collects-1) != 0 {
		return false
	}
	for _, capability := range stable.Capabilities {
		if capability.Status == "timeout" || capability.Reason == "request_failed" {
			return true
		}
	}
	return false
}

type localAdapter struct {
	collector
	provider Capability
}

func NewLocal(config Config) Adapter {
	return &localAdapter{
		collector: collector{config: config.normalized(), previous: map[string]float64{}},
		provider:  Capability{Status: "partial", Reason: "provider_unknown"},
	}
}
func (*localAdapter) Name() string { return "local" }
func (a *localAdapter) Collect(ctx context.Context, level int) Snapshot {
	a.mu.Lock()
	defer a.mu.Unlock()
	snapshot := a.collect(ctx, level)
	snapshot.Identity.Provider = "local"
	snapshot.Capabilities["provider"] = a.provider
	return snapshot
}
func (a *collector) collect(ctx context.Context, level int) Snapshot {
	snapshot := Snapshot{
		Networks:     []NetworkDevice{},
		Counters:     []Counter{},
		Topology:     Topology{Levels: []TopologyLevel{}},
		Transport:    TransportEvidence{Name: "unknown"},
		Capabilities: map[string]Capability{},
	}
	a.network(ctx, level, &snapshot)
	a.fabric(&snapshot)
	if _, ok := a.config.Pseudonym("probe", "identity"); ok {
		snapshot.Capabilities["identity_join"] = Capability{Status: "available"}
	} else {
		reason := a.config.KeyReason
		if reason == "" {
			reason = "missing_redaction_key"
		}
		snapshot.Capabilities["identity_join"] = Capability{Status: "partial", Reason: reason}
	}
	next := map[string]float64{}
	for _, counter := range snapshot.Counters {
		if counter.Value == nil {
			continue
		}
		key := counter.Device + "\x00" + counter.Name
		if old, ok := a.previous[key]; ok && counter.Monotonic && *counter.Value < old {
			snapshot.Capabilities["network"] = Capability{
				Status: "partial",
				Reason: "counter_reset",
			}
		}
		next[key] = *counter.Value
	}
	a.previous = next
	return snapshot
}
