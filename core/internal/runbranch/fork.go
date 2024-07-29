package runbranch

import (
	"context"

	"github.com/Khan/genqlient/graphql"
	"github.com/wandb/wandb/core/pkg/service"
)

type ForkBranch struct {
	ctx         context.Context
	client      graphql.Client
	metricRunID string
	metricName  string
	metricValue float64
}

func NewForkBranch(
	ctx context.Context,
	client graphql.Client,
	runid string,
	metricName string,
	metricValue float64,
) *ForkBranch {
	return &ForkBranch{
		ctx:         ctx,
		client:      client,
		metricRunID: runid,
		metricName:  metricName,
		metricValue: metricValue,
	}
}

func (fb *ForkBranch) GetUpdates(
	params *RunParams,
	runpath RunPath,
) (*RunParams, error) {
	if fb.metricName != "_step" {
		return nil, &BranchError{
			Err: nil,
			Response: &service.ErrorInfo{
				Code:    service.ErrorInfo_UNSUPPORTED,
				Message: "fork_from only supports `_step` metric name currently",
			},
		}
	}

	if fb.metricRunID == runpath.RunID {
		return nil, &BranchError{
			Err: nil,
			Response: &service.ErrorInfo{
				Code:    service.ErrorInfo_USAGE,
				Message: "fork_from run id must be different from current run id",
			},
		}
	}

	r := &RunParams{}
	r.Merge(params)
	r.Forked = true
	r.StartingStep = int64(fb.metricValue) + 1
	return r, nil
}
