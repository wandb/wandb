package monitor

import (
	"github.com/shirou/gopsutil/v4/net"
	spb "github.com/wandb/wandb/core/pkg/service_go_proto"
	"google.golang.org/protobuf/types/known/timestamppb"
)

type Network struct {
	name     string
	sentInit int
	recvInit int
}

func NewNetwork() *Network {
	nw := &Network{name: "network"}

	netIOCounters, err := net.IOCounters(false)
	if err == nil {
		nw.sentInit = int(netIOCounters[0].BytesSent)
		nw.recvInit = int(netIOCounters[0].BytesRecv)
	}

	return nw
}

func (n *Network) Name() string { return n.name }

func (n *Network) Sample() (*spb.StatsRecord, error) {
	metrics := make(map[string]any)
	netIOCounters, err := net.IOCounters(false)
	if err != nil {
		return nil, err
	}
	metrics["network.sent"] = float64(int(netIOCounters[0].BytesSent) - n.sentInit)
	metrics["network.recv"] = float64(int(netIOCounters[0].BytesRecv) - n.recvInit)

	if len(metrics) == 0 {
		return nil, nil
	}

	return marshal(metrics, timestamppb.Now()), nil
}

func (n *Network) IsAvailable() bool { return true }

func (n *Network) Probe() *spb.MetadataRequest {
	// todo: network info
	return nil
}
