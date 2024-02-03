package monitor

import (
	"sync"

	"github.com/shirou/gopsutil/v3/net"

	"github.com/wandb/wandb/core/pkg/service"
)

type Network struct {
	name     string
	metrics  map[string][]float64
	settings *service.Settings
	mutex    sync.RWMutex
	sentInit int
	recvInit int
	lastSent int
	lastRecv int
}

func NewNetwork(settings *service.Settings) *Network {
	nw := &Network{
		name:     "network",
		metrics:  map[string][]float64{},
		settings: settings,
	}

	netIOCounters, err := net.IOCounters(false)
	if err == nil {
		nw.sentInit = int(netIOCounters[0].BytesSent)
		nw.recvInit = int(netIOCounters[0].BytesRecv)
		nw.lastSent = int(netIOCounters[0].BytesSent)
		nw.lastRecv = int(netIOCounters[0].BytesRecv)
	}

	return nw
}

func (n *Network) Name() string { return n.name }

func (n *Network) SampleMetrics() {
	n.mutex.Lock()
	defer n.mutex.Unlock()

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

		n.metrics["network.upload_speed"] = append(
			n.metrics["network.upload_speed"],
			float64((int(netIOCounters[0].BytesSent)-n.lastSent)/2),
		)

		n.lastSent = int(netIOCounters[0].BytesSent)
		n.metrics["network.download_speed"] = append(
			n.metrics["network.download_speed"],
			float64((int(netIOCounters[0].BytesRecv)-n.lastRecv)/2),
		)
		n.lastRecv = int(netIOCounters[0].BytesRecv)
	}

}

func (n *Network) AggregateMetrics() map[string]float64 {
	n.mutex.Lock()
	defer n.mutex.Unlock()

	aggregates := make(map[string]float64)
	for metric, samples := range n.metrics {
		if len(samples) > 0 {
			aggregates[metric] = samples[len(samples)-1]
		}
	}
	return aggregates
}

func (n *Network) ClearMetrics() {
	n.mutex.Lock()
	defer n.mutex.Unlock()

	n.metrics = map[string][]float64{}
}

func (n *Network) IsAvailable() bool { return true }

func (n *Network) Probe() *service.MetadataRequest {
	// todo: network info
	return nil
}
