//go:build !linux && !amd64

package monitor

import (
	"github.com/wandb/wandb/nexus/pkg/service"
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

func (c *GPUNvidia) Name() string { return c.name }

func (c *GPUNvidia) SampleMetrics() {}

func (c *GPUNvidia) AggregateMetrics() map[string]float64 {
	return map[string]float64{}
}

func (c *GPUNvidia) ClearMetrics() {}

func (c *GPUNvidia) IsAvailable() bool { return false }

func (c *GPUNvidia) Probe() map[string]map[string]interface{} {
	info := make(map[string]map[string]interface{})
	return info
}
