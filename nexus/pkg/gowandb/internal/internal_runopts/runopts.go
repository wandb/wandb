package internal_runopts

import (
	"github.com/wandb/wandb/nexus/pkg/gowandb/runconfig"
)

type RunParams struct {
	Config *runconfig.Config
	Name   *string
	RunID  *string
}
