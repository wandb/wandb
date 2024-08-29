//go:build !linux || libwandb_core

package monitor

import (
	"github.com/wandb/wandb/core/pkg/observability"
	spb "github.com/wandb/wandb/core/pkg/service_go_proto"
)

type GPUNvidia struct {
	name             string
	pid              int32
	samplingInterval float64
	logger           *observability.CoreLogger
}

func NewGPUNvidia(logger *observability.CoreLogger, pid int32, samplingInterval float64) *GPUNvidia {
	gpu := &GPUNvidia{
		name:             "gpu",
		pid:              pid,
		samplingInterval: samplingInterval,
		logger:           logger,
	}

	return gpu
}

func (g *GPUNvidia) Name() string { return g.name }

func (g *GPUNvidia) Sample() (map[string]any, error) { return nil, nil }

func (g *GPUNvidia) IsAvailable() bool { return false }

func (g *GPUNvidia) Probe() *spb.MetadataRequest {
	return nil
}

type GPUAMD struct {
	name string
}

func NewGPUAMD() *GPUAMD {
	gpu := &GPUAMD{name: "gpu"}

	return gpu
}

func (g *GPUAMD) Name() string { return g.name }

func (g *GPUAMD) Sample() (map[string]any, error) { return nil, nil }

func (g *GPUAMD) IsAvailable() bool { return false }

func (g *GPUAMD) Probe() *spb.MetadataRequest {
	return nil
}
