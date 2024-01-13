// sub-package for gowandb run options
package runopts

import (
	"github.com/wandb/wandb/core/internal/gowandb/client/runconfig"
	pb "github.com/wandb/wandb/core/internal/wandb_core_go_proto"
)

type RunParams struct {
	Config    *runconfig.Config
	Name      *string
	RunID     *string
	Project   *string
	Telemetry *pb.TelemetryRecord
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

func WithProject(project string) RunOption {
	return func(p *RunParams) {
		p.Project = &project
	}
}
