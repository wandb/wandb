package runbranch

import spb "github.com/wandb/wandb/core/pkg/service_go_proto"

// ForkBranch is a used to manage the state of the changes that need to be
// applied to a run when a fork from a previous run is requested.
type ForkBranch struct {

	// metricRunID is the id of the run to fork from
	metricRunID string

	// metricName is the name of the metric used as the fork point
	// Currently only `_step` is supported
	metricName string

	// metricValue is the value of the metric used as the fork point
	metricValue float64
}

func NewForkBranch(
	runid string,
	metricName string,
	metricValue float64,
) *ForkBranch {

	return &ForkBranch{
		metricRunID: runid,
		metricName:  metricName,
		metricValue: metricValue,
	}
}

// UpdateForFork sets run metadata for forking.
func (fb *ForkBranch) UpdateForFork(params *RunParams) error {
	if fb.metricName != "_step" {
		return &BranchError{
			Err: nil,
			Response: &spb.ErrorInfo{
				Code:    spb.ErrorInfo_UNSUPPORTED,
				Message: "fork_from only supports `_step` metric name currently",
			},
		}
	}

	if fb.metricRunID == params.RunID {
		return &BranchError{
			Err: nil,
			Response: &spb.ErrorInfo{
				Code:    spb.ErrorInfo_USAGE,
				Message: "fork_from run id must be different from current run id",
			},
		}
	}

	params.Forked = true
	params.StartingStep = int64(fb.metricValue) + 1
	return nil
}
