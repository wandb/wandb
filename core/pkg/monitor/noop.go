//go:build darwin || freebsd || windows

package monitor

import (
	"github.com/wandb/wandb/core/internal/observability"
	spb "github.com/wandb/wandb/core/pkg/service_go_proto"
)

// Trainium is a dummy implementation of the Asset interface for Trainium.
type Trainium struct {
	name                    string
	pid                     int32
	samplingInterval        float64
	logger                  *observability.CoreLogger
	neuronMonitorConfigPath string
}

func NewTrainium(
	logger *observability.CoreLogger,
	pid int32,
	samplingInterval float64,
	neuronMonitorConfigPath string,
) *Trainium {
	return &Trainium{
		name:                    "trainium",
		pid:                     pid,
		samplingInterval:        samplingInterval,
		logger:                  logger,
		neuronMonitorConfigPath: neuronMonitorConfigPath,
	}
}

func (t *Trainium) Name() string { return t.name }

func (t *Trainium) Sample() (*spb.StatsRecord, error) { return nil, nil }

func (t *Trainium) IsAvailable() bool { return false }

func (t *Trainium) Probe() *spb.MetadataRequest {
	return nil
}

// TPU is a dummy implementation of the Asset interface for TPUs.
type TPU struct {
	name string
}

func NewTPU() *TPU {
	return &TPU{name: "tpu"}
}

func (t *TPU) Name() string { return t.name }

func (t *TPU) Sample() (*spb.StatsRecord, error) { return nil, nil }

func (t *TPU) IsAvailable() bool { return false }

func (t *TPU) Probe() *spb.MetadataRequest {
	return nil
}
