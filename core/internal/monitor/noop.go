//go:build !linux || libwandb_core

package monitor

import pb "github.com/wandb/wandb/core/internal/wandb_core_go_proto"

type GPUNvidia struct {
	name     string
	settings *pb.Settings
}

func NewGPUNvidia(settings *pb.Settings) *GPUNvidia {
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

func (g *GPUNvidia) Probe() *pb.MetadataRequest {
	return nil
}

type GPUAMD struct {
	name     string
	settings *pb.Settings
}

func NewGPUAMD(settings *pb.Settings) *GPUAMD {
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

func (g *GPUAMD) Probe() *pb.MetadataRequest {
	return nil
}
