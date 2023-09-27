// sub-package for gowandb run options
package runopts

import (
	"github.com/wandb/wandb/nexus/pkg/gowandb/runconfig"
	"github.com/wandb/wandb/nexus/pkg/gowandb/internal/internal_runopts"
)

type RunOption func(*internal_runopts.RunParams)

func WithConfig(config runconfig.Config) RunOption {
	return func(p *internal_runopts.RunParams) {
		p.Config = &config
	}
}

func WithName(name string) RunOption {
	return func(p *internal_runopts.RunParams) {
		p.Name = &name
	}
}

func WithRunID(runID string) RunOption {
	return func(p *internal_runopts.RunParams) {
		p.RunID = &runID
	}
}
