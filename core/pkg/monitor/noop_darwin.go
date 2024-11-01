//go:build darwin

package monitor

import (
	"github.com/wandb/wandb/core/internal/observability"
	spb "github.com/wandb/wandb/core/pkg/service_go_proto"
)

// GPUNvidia is a dummy implementation of the Asset interface for Nvidia GPUs.
type GPUNvidia struct {
	name             string
	pid              int32
	samplingInterval float64
	logger           *observability.CoreLogger
}

func NewGPUNvidia(
	logger *observability.CoreLogger,
	pid int32,
	samplingInterval float64,
	cmdPath string,
) *GPUNvidia {
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

// GPUAMD is a dummy implementation of the Asset interface for AMD GPUs.
type GPUAMD struct {
	name   string
	logger *observability.CoreLogger
}

func NewGPUAMD(logger *observability.CoreLogger) *GPUAMD {
	return &GPUAMD{
		name:   "gpu",
		logger: logger,
	}
}

func (g *GPUAMD) Name() string { return g.name }

func (g *GPUAMD) Sample() (map[string]any, error) { return nil, nil }

func (g *GPUAMD) IsAvailable() bool { return false }

func (g *GPUAMD) Probe() *spb.MetadataRequest {
	return nil
}

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

func (t *Trainium) Sample() (map[string]any, error) { return nil, nil }

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

func (t *TPU) Sample() (map[string]any, error) { return nil, nil }

func (t *TPU) IsAvailable() bool { return false }

func (t *TPU) Probe() *spb.MetadataRequest {
	return nil
}
