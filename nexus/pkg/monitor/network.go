package monitor

import (
	"sync"

	"github.com/shirou/gopsutil/v3/net"

	"github.com/wandb/wandb/nexus/pkg/service"
)

type Network struct {
	name     string
	metrics  map[string][]float64
	settings *service.Settings
	mutex    sync.RWMutex
	sentInit int
	recvInit int
}

func NewNetwork(settings *service.Settings) *Network {
	metrics := map[string][]float64{}

	nw := &Network{
		name:     "network",
		metrics:  metrics,
		settings: settings,
	}

	netIOCounters, err := net.IOCounters(false)
	if err == nil {
		nw.sentInit = int(netIOCounters[0].BytesSent)
		nw.recvInit = int(netIOCounters[0].BytesRecv)
	}

	return nw
}

func (n *Network) Name() string { return n.name }

func (n *Network) SampleMetrics() {
	n.mutex.RLock()
	defer n.mutex.RUnlock()

	netIOCounters, err := net.IOCounters(false)
	if err == nil {
		n.metrics["network.sent"] = append(
			n.metrics["network.sent"],
			float64(int(netIOCounters[0].BytesSent)-n.sentInit),
		)
		n.metrics["network.recv"] = append(
			n.metrics["network.recv"],
			float64(int(netIOCounters[0].BytesRecv)-n.recvInit),
		)
	}

}

func (n *Network) AggregateMetrics() map[string]float64 {
	n.mutex.RLock()
	defer n.mutex.RUnlock()

	aggregates := make(map[string]float64)
	for metric, samples := range n.metrics {
		if len(samples) > 0 {
			aggregates[metric] = samples[len(samples)-1]
		}
	}
	return aggregates
}

func (n *Network) ClearMetrics() {
	n.mutex.RLock()
	defer n.mutex.RUnlock()

	n.metrics = map[string][]float64{}
}

func (n *Network) IsAvailable() bool { return true }

func (n *Network) Probe() map[string]map[string]interface{} {
	info := make(map[string]map[string]interface{})
	// todo: network info
	return info
}
