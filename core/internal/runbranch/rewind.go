package runbranch

import (
	"context"
	"fmt"

	"github.com/Khan/genqlient/graphql"
	"github.com/wandb/wandb/core/internal/filestream"
	"github.com/wandb/wandb/core/internal/gql"
	"github.com/wandb/wandb/core/internal/nullify"
	"github.com/wandb/wandb/core/internal/runconfig"
	spb "github.com/wandb/wandb/core/pkg/service_go_proto"
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

// UpdateForRewind modifies run metadata for rewinding.
//
// The metadata should be initialized as if creating a fresh run,
// specifically with Entity, Project and RunID fields set.
//
// On error, the metadata may have been partially modified
// and must be discarded.
func (rb RewindBranch) UpdateForRewind(
	params *RunParams,
	config *runconfig.RunConfig,
) error {
	if rb.branch.RunID != params.RunID {
		err := fmt.Errorf(
			"rewind run id %s does not match run id %s",
			rb.branch.RunID,
			params.RunID)
		info := &spb.ErrorInfo{
			Code:    spb.ErrorInfo_USAGE,
			Message: err.Error(),
		}
		return &BranchError{Err: err, Response: info}
	}

	if rb.branch.MetricName != "_step" {
		err := fmt.Errorf("rewind only supports `_step` metric name currently")
		info := &spb.ErrorInfo{
			Code:    spb.ErrorInfo_UNSUPPORTED,
			Message: err.Error(),
		}
		return &BranchError{Err: err, Response: info}
	}

	response, err := gql.RewindRun(
		rb.ctx,
		rb.client,
		params.RunID,
		nullify.NilIfZero(params.Entity),
		nullify.NilIfZero(params.Project),
		rb.branch.MetricName,
		rb.branch.MetricValue,
	)

	if err != nil {
		return &BranchError{
			Err: err,
			Response: &spb.ErrorInfo{
				Code:    spb.ErrorInfo_COMMUNICATION,
				Message: fmt.Sprintf("failed to rewind run: %s", err),
			},
		}
	}

	if response.GetRewindRun() == nil || response.GetRewindRun().GetRewoundRun() == nil {
		return &BranchError{
			Err: fmt.Errorf("run not found"),
			Response: &spb.ErrorInfo{
				Code:    spb.ErrorInfo_COMMUNICATION,
				Message: "failed to rewind run: run not found",
			},
		}
	}

	data := response.GetRewindRun().GetRewoundRun()

	if data.GetHistoryLineCount() != nil {
		if params.FileStreamOffset == nil {
			params.FileStreamOffset = make(filestream.FileStreamOffsetMap)
		}

		params.FileStreamOffset[filestream.HistoryChunk] =
			*data.GetHistoryLineCount()
	}

	if data.GetProject() != nil {
		params.Project = data.GetProject().Name
		params.Entity = data.GetProject().GetEntity().Name
	}

	if data.GetConfig() != nil {
		var oldConfig map[string]any
		oldConfig, err = processConfig(data.GetConfig())

		if err == nil {
			config.MergeResumedConfig(oldConfig)
		}
	}

	if data.GetId() != "" {
		params.StorageID = data.GetId()
	}
	if data.GetName() != "" {
		params.RunID = data.GetName()
	}
	if name := data.GetDisplayName(); name != nil && *name != "" {
		params.DisplayName = *name
	}
	if id := data.GetSweepName(); id != nil && *id != "" {
		params.SweepID = *id
	}
	params.StartingStep = int64(rb.branch.MetricValue) + 1
	params.Forked = true

	return err
}
