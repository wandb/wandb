//go:build !linux || libwandb_core

package monitor

import (
	"github.com/wandb/wandb/core/pkg/service"
)

type GPUNvidia struct {
	name     string
	settings *service.Settings
}

func NewGPUNvidia(settings *service.Settings) *GPUNvidia {
	gpu := &GPUNvidia{
		name:     "gpu",
		settings: settings,
	}

	return gpu
}

func (g *GPUNvidia) Name() string { return g.name }

func (g *GPUNvidia) SampleMetrics() {}

func (g *GPUNvidia) AggregateMetrics() map[string]float64 {
	return map[string]float64{}
}

func (g *GPUNvidia) ClearMetrics() {}

func (g *GPUNvidia) IsAvailable() bool { return false }

func (g *GPUNvidia) Probe() *service.MetadataRequest {
	return nil
}

type GPUAMD struct {
	name     string
	settings *service.Settings
}

func NewGPUAMD(settings *service.Settings) *GPUAMD {
	gpu := &GPUAMD{
		name:     "gpu",
		settings: settings,
	}

	return gpu
}

func (g *GPUAMD) Name() string { return g.name }

func (g *GPUAMD) SampleMetrics() {}

func (g *GPUAMD) AggregateMetrics() map[string]float64 {
	return map[string]float64{}
}

func (g *GPUAMD) ClearMetrics() {}

func (g *GPUAMD) IsAvailable() bool { return false }

func (g *GPUAMD) Probe() *service.MetadataRequest {
	return nil
}
