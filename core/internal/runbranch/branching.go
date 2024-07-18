package runbranch

import (
	"github.com/wandb/wandb/core/pkg/service"
)

type BranchingState struct {
	RunID     string
	StepName  string
	StepValue float64
	Mode      string
	Type      string
}

func NewBranchingState(resume string, rewind, fork *service.RunMoment) *BranchingState {
	// check that only one of resume, rewind, or fork is set
	if (resume != "" && rewind != nil) || (resume != "" && fork != nil) || (rewind != nil && fork != nil) {
		return nil
	}

	if resume != "" {
		return &BranchingState{
			Mode: resume,
			Type: "resume",
		}
	}

	if rewind != nil {
		return &BranchingState{
			RunID:     rewind.GetRun(),
			StepName:  rewind.GetMetric(),
			StepValue: rewind.GetValue(),
			Type:      "rewind",
		}
	}

	if fork != nil {
		return &BranchingState{
			RunID:     fork.GetRun(),
			StepName:  fork.GetMetric(),
			StepValue: fork.GetValue(),
			Type:      "fork",
		}
	}

	return &BranchingState{
		Type: "none",
	}

}
