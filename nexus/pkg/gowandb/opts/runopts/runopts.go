// sub-package for gowandb run options
package runopts

import (
	"github.com/wandb/wandb/nexus/pkg/gowandb/runconfig"
	"github.com/wandb/wandb/nexus/pkg/service"
)

type RunParams struct {
	Config    *runconfig.Config
	Name      *string
	RunID     *string
	Telemetry *service.TelemetryRecord
}

type RunOption func(*RunParams)

func WithConfig(config runconfig.Config) RunOption {
	return func(p *RunParams) {
		p.Config = &config
	}
}

func WithName(name string) RunOption {
	return func(p *RunParams) {
		p.Name = &name
	}
}

func WithRunID(runID string) RunOption {
	return func(p *RunParams) {
		p.RunID = &runID
	}
}
