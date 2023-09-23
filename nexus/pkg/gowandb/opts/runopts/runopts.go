// sub-package for gowandb run options
package runopts

import (
	"github.com/wandb/wandb/nexus/pkg/gowandb/runconfig"
)

type RunParams struct {
	Config *runconfig.Config
}

type RunOption func(*RunParams)

func WithConfig() RunOption {
	return func(s *RunParams) {
	}
}
