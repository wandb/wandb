package runresume

import "github.com/wandb/wandb/core/pkg/service"

func (r *RunState) UpdateRewind() error {
	return nil
}

func (r *RunState) applyRewind(record *service.RunRecord) {
}
