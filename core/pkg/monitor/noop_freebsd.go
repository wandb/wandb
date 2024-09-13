//go:build freebsd

package monitor

import (
	"github.com/wandb/wandb/core/pkg/observability"
	spb "github.com/wandb/wandb/core/pkg/service_go_proto"
)

// GPUApple is a dummy implementation of the Asset interface for Apple GPUs.
type GPUApple struct {
	name string
}

func NewGPUApple() *GPUApple {
	return &GPUApple{name: "gpu"}
}

func (g *GPUApple) Name() string { return g.name }

func (g *GPUApple) Sample() (map[string]any, error) { return nil, nil }

func (g *GPUApple) IsAvailable() bool { return false }

func (g *GPUApple) Probe() *spb.MetadataRequest {
	return nil
}

// GPUNvidia is a dummy implementation of the Asset interface for Nvidia GPUs.
type GPUNvidia struct {
	name             string
	pid              int32
	samplingInterval float64
	logger           *observability.CoreLogger
}

func NewGPUNvidia(logger *observability.CoreLogger, pid int32, samplingInterval float64) *GPUNvidia {
	return &GPUNvidia{
		name:             "gpu",
		pid:              pid,
		samplingInterval: samplingInterval,
		logger:           logger,
	}
}

func (g *GPUNvidia) Name() string { return g.name }

func (g *GPUNvidia) Sample() (map[string]any, error) { return nil, nil }

func (g *GPUNvidia) IsAvailable() bool { return false }

func (g *GPUNvidia) Probe() *spb.MetadataRequest {
	return nil
}
