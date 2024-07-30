package runbranch

import (
	"context"
	"fmt"

	"github.com/Khan/genqlient/graphql"
	"github.com/wandb/simplejsonext"
	"github.com/wandb/wandb/core/internal/filestream"
	"github.com/wandb/wandb/core/internal/gql"
	"github.com/wandb/wandb/core/pkg/service"
	"github.com/wandb/wandb/core/pkg/utils"
)

type RewindBranch struct {
	ctx    context.Context
	client graphql.Client
	branch BranchPoint
}

func NewRewindBranch(
	ctx context.Context,
	client graphql.Client,
	runid string,
	metricName string,
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

//gocyclo:ignore
func (rb RewindBranch) GetUpdates(
	params *RunParams,
	runpath RunPath,
) (*RunParams, error) {
	if rb.branch.RunID != runpath.RunID {
		err := fmt.Errorf("rewind run id %s does not match run id %s", rb.branch.RunID, runpath.RunID)
		info := &service.ErrorInfo{
			Code:    service.ErrorInfo_USAGE,
			Message: err.Error(),
		}
		return nil, &BranchError{Err: err, Response: info}
	}

	if rb.branch.MetricName != "_step" {
		err := fmt.Errorf("rewind only supports `_step` metric name currently")
		info := &service.ErrorInfo{
			Code:    service.ErrorInfo_UNSUPPORTED,
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
		info := &service.ErrorInfo{
			Code:    service.ErrorInfo_COMMUNICATION,
			Message: fmt.Sprintf("failed to rewind run: %s", err),
		}
		return nil, &BranchError{Err: err, Response: info}
	}

	if response.GetRewindRun() == nil || response.GetRewindRun().GetRewoundRun() == nil {
		info := &service.ErrorInfo{
			Code:    service.ErrorInfo_COMMUNICATION,
			Message: "failed to rewind run: run not found",
		}
		return nil, &BranchError{Err: fmt.Errorf("run not found"), Response: info}
	}

	r := &RunParams{}
	r.Merge(params)

	data := response.GetRewindRun().GetRewoundRun()

	if data.GetId() != "" {
		r.StorageID = data.GetId()
	}

	if data.GetName() != "" {
		r.RunID = data.GetName()
	}

	if data.GetDisplayName() != nil {
		r.DisplayName = *data.GetDisplayName()
	}

	if data.GetSweepName() != nil {
		r.SweepID = *data.GetSweepName()
	}

	if data.GetProject() != nil {
		if data.GetProject().GetName() != "" {
			r.Project = data.GetProject().GetName()
		}
		entity := data.GetProject().GetEntity()
		if entity.GetName() != "" {
			r.Entity = entity.GetName()
		}
	}

	if data.GetHistoryLineCount() != nil {
		if r.FileStreamOffset == nil {
			r.FileStreamOffset = make(filestream.FileStreamOffsetMap)
		}
		r.FileStreamOffset[filestream.HistoryChunk] = *data.GetHistoryLineCount()
	}

	r.StartingStep = int64(rb.branch.MetricValue) + 1
	r.Forked = true

	r.Config, err = parseConfig(data.GetConfig())

	return r, err
}

func parseConfig(config *string) (map[string]any, error) {
	// Get Config information

	if config != nil {
		// If we are unable to parse the config, we should fail if resume is set to
		// must for any other case of resume status, it is fine to ignore it
		cfgVal, err := simplejsonext.UnmarshalString(*config)
		if err != nil {
			return nil, fmt.Errorf("failed to unmarshal config: %s", err)
		}

		var cfg map[string]any
		switch x := cfgVal.(type) {
		case nil: // OK, cfg is nil
		case map[string]any:
			cfg = x
		default:
			return nil, fmt.Errorf(
				"got type %T for %s",
				x, *config,
			)
		}

		result := make(map[string]any)
		for key, value := range cfg {
			valueDict, ok := value.(map[string]any)
			if !ok {
				return nil, fmt.Errorf("unexpected type %T for %s", value, key)
			} else if val, ok := valueDict["value"]; ok {
				result[key] = val
			}
		}
		return result, nil
	}
	return nil, nil
}
