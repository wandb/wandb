//go:build !linux || (linux && musl) || libwandb_core

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
