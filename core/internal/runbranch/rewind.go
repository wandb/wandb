package runbranch

import (
	"context"
	"fmt"

	"github.com/Khan/genqlient/graphql"
	"github.com/wandb/wandb/core/internal/filestream"
	"github.com/wandb/wandb/core/internal/gql"
	spb "github.com/wandb/wandb/core/pkg/service_go_proto"
	"github.com/wandb/wandb/core/pkg/utils"
)

// RewindBranch is a used to manage the state of the changes that need to be
// applied to a run when a rewind from a previous run is requested.s
type RewindBranch struct {
	ctx    context.Context
	client graphql.Client
	branch BranchPoint
}

func NewRewindBranch(

	ctx context.Context,
	client graphql.Client,

	// runid is the id of the run to rewind
	runid string,

	// metricName is the name of the metric used as the rewind point
	metricName string,

	// metricValue is the value of the metric used as the rewind point
	metricValue float64,

) *RewindBranch {

	return &RewindBranch{
		ctx:    ctx,
		client: client,
		branch: BranchPoint{
			RunID:       runid,
			MetricName:  metricName,
			MetricValue: metricValue,
		},
	}
}

// ApplyChanges applies the changes to the run params based on the rewind
// information returned from the server.
func (rb RewindBranch) ApplyChanges(
	params *RunParams,
	runpath RunPath,
) (*RunParams, error) {

	if rb.branch.RunID != runpath.RunID {
		err := fmt.Errorf(
			"rewind run id %s does not match run id %s",
			rb.branch.RunID,
			runpath.RunID)
		info := &spb.ErrorInfo{
			Code:    spb.ErrorInfo_USAGE,
			Message: err.Error(),
		}
		return nil, &BranchError{Err: err, Response: info}
	}

	if rb.branch.MetricName != "_step" {
		err := fmt.Errorf("rewind only supports `_step` metric name currently")
		info := &spb.ErrorInfo{
			Code:    spb.ErrorInfo_UNSUPPORTED,
			Message: err.Error(),
		}
		return nil, &BranchError{Err: err, Response: info}
	}

	response, err := gql.RewindRun(
		rb.ctx,
		rb.client,
		runpath.RunID,
		utils.NilIfZero(runpath.Entity),
		utils.NilIfZero(runpath.Project),
		rb.branch.MetricName,
		rb.branch.MetricValue,
	)

	if err != nil {
		return nil, &BranchError{
			Err: err,
			Response: &spb.ErrorInfo{
				Code:    spb.ErrorInfo_COMMUNICATION,
				Message: fmt.Sprintf("failed to rewind run: %s", err),
			},
		}
	}

	if response.GetRewindRun() == nil || response.GetRewindRun().GetRewoundRun() == nil {
		return nil, &BranchError{
			Err: fmt.Errorf("run not found"),
			Response: &spb.ErrorInfo{
				Code:    spb.ErrorInfo_COMMUNICATION,
				Message: "failed to rewind run: run not found",
			},
		}
	}

	data := response.GetRewindRun().GetRewoundRun()

	r := params.Clone()

	filestreamOffset := make(filestream.FileStreamOffsetMap)
	if data.GetHistoryLineCount() != nil {
		filestreamOffset[filestream.HistoryChunk] = *data.GetHistoryLineCount()
	}

	var projectName, entityName string
	if data.GetProject() != nil {
		projectName = data.GetProject().GetName()
		entity := data.GetProject().GetEntity()
		entityName = entity.GetName()
	}

	var config map[string]any
	if data.GetConfig() != nil {
		config, err = processConfig(data.GetConfig())
	}

	r.Merge(
		&RunParams{
			StorageID:        data.GetId(),
			RunID:            data.GetName(),
			DisplayName:      utils.ZeroIfNil(data.GetDisplayName()),
			SweepID:          utils.ZeroIfNil(data.GetSweepName()),
			StartingStep:     int64(rb.branch.MetricValue) + 1,
			Forked:           true,
			FileStreamOffset: filestreamOffset,
			Project:          projectName,
			Entity:           entityName,
			Config:           config,
		},
	)

	return r, err
}
