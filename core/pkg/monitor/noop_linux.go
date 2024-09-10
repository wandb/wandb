//go:build linux

package monitor

import spb "github.com/wandb/wandb/core/pkg/service_go_proto"

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
