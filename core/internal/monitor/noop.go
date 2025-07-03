//go:build darwin || freebsd || windows

package monitor

import (
	"context"

	"github.com/wandb/wandb/core/internal/observability"
	spb "github.com/wandb/wandb/core/pkg/service_go_proto"
)

// Trainium is a dummy implementation of the Resource interface for Trainium.
type Trainium struct{}

func NewTrainium(
	logger *observability.CoreLogger,
	pid int32,
	samplingInterval float64,
	neuronMonitorConfigPath string,
) *Trainium {
	return nil
}

func (t *Trainium) Sample() (*spb.StatsRecord, error) { return nil, nil }

func (t *Trainium) Probe(_ context.Context) *spb.EnvironmentRecord {
	return nil
}

// TPU is a dummy implementation of the Resource interface for TPUs.
type TPU struct{}

func NewTPU() *TPU {
	return nil
}

func (t *TPU) Sample() (*spb.StatsRecord, error) { return nil, nil }

func (t *TPU) Probe(_ context.Context) *spb.EnvironmentRecord {
	return nil
}
