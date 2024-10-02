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

// ApplyChanges applies the changes to the run params based on the fork
// information
func (fb *ForkBranch) ApplyChanges(
	params *RunParams,
	runpath RunPath,
) (*RunParams, error) {

	if fb.metricName != "_step" {
		return nil, &BranchError{
			Err: nil,
			Response: &spb.ErrorInfo{
				Code:    spb.ErrorInfo_UNSUPPORTED,
				Message: "fork_from only supports `_step` metric name currently",
			},
		}
	}

	if fb.metricRunID == runpath.RunID {
		return nil, &BranchError{
			Err: nil,
			Response: &spb.ErrorInfo{
				Code:    spb.ErrorInfo_USAGE,
				Message: "fork_from run id must be different from current run id",
			},
		}
	}

	r := params.Clone()
	r.Merge(
		&RunParams{
			Forked:       true,
			StartingStep: int64(fb.metricValue) + 1,
		},
	)
	return r, nil
}
