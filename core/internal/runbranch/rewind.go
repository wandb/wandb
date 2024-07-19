package runbranch

import "github.com/wandb/wandb/core/pkg/service"

func (r *State) updateStateRewindMode(_ *BranchingState) error {
	return nil
}

func (r *State) updateRunRewindMode(record *service.RunRecord) {
}
