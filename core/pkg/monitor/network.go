package monitor

import (
	"sync"

	"github.com/shirou/gopsutil/v4/net"
	spb "github.com/wandb/wandb/core/pkg/service_go_proto"
)

type Network struct {
	name     string
	metrics  map[string][]float64
	mutex    sync.RWMutex
	sentInit int
	recvInit int
}

func NewNetwork() *Network {
	nw := &Network{
		name:    "network",
		metrics: map[string][]float64{},
	}

	netIOCounters, err := net.IOCounters(false)
	if err == nil {
		nw.sentInit = int(netIOCounters[0].BytesSent)
		nw.recvInit = int(netIOCounters[0].BytesRecv)
	}

	return nw
}

func (n *Network) Name() string { return n.name }

func (n *Network) SampleMetrics() error {
	n.mutex.Lock()
	defer n.mutex.Unlock()

	netIOCounters, err := net.IOCounters(false)
	if err != nil {
		return err
	}
	n.metrics["network.sent"] = append(
		n.metrics["network.sent"],
		float64(int(netIOCounters[0].BytesSent)-n.sentInit),
	)
	n.metrics["network.recv"] = append(
		n.metrics["network.recv"],
		float64(int(netIOCounters[0].BytesRecv)-n.recvInit),
	)

	return nil
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

func (n *Network) Probe() *spb.MetadataRequest {
	// todo: network info
	return nil
}
