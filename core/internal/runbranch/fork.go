package runbranch

import "github.com/wandb/wandb/core/pkg/service"

func (r *State) updateStateForkMode(_ *BranchingState) error {
	return nil
}

func (r *State) updateRunForkMode(record *service.RunRecord) {
}
