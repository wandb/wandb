package runbranch

import (
	"context"
	"errors"
	"fmt"

	"github.com/Khan/genqlient/graphql"
	"github.com/wandb/simplejsonext"
	"github.com/wandb/wandb/core/internal/filestream"
	"github.com/wandb/wandb/core/internal/gql"
	"github.com/wandb/wandb/core/pkg/service"
	"github.com/wandb/wandb/core/pkg/utils"
)

type RewindBranch struct {
	ctx         context.Context
	client      graphql.Client
	runid       string
	metricName  string
	metricValue float64
}

func NewRewindBranch(
	ctx context.Context,
	client graphql.Client,
	runid string,
	metricName string,
	metricValue float64,
) *RewindBranch {
	return &RewindBranch{
		ctx:         ctx,
		client:      client,
		runid:       runid,
		metricName:  metricName,
		metricValue: metricValue,
	}
}

func (r RewindBranch) GetUpdates(
	params *RunParams,
	runpath RunPath,
) (*RunParams, error) {
	// TODO: check that runid matches runpath.RunID

	response, err := gql.RewindRun(
		r.ctx,
		r.client,
		runpath.RunID,
		utils.NilIfZero(runpath.Entity),
		utils.NilIfZero(runpath.Project),
		r.metricName,
		r.metricValue,
	)
	if err != nil {
		info := &service.ErrorInfo{
			Code:    service.ErrorInfo_COMMUNICATION,
			Message: fmt.Sprintf("Failed to rewind run: %s", err),
		}
		return nil, &BranchError{Err: err, Response: info}
	}

	// TODO: check errors
	data := response.GetRewindRun().GetRewoundRun()

	fmt.Println(data)

	if data.GetId() != "" {
		params.StorageID = data.GetId()
	}
	if data.GetName() != "" {
		params.RunID = data.GetName()
	}
	if data.GetDisplayName() != nil {
		params.DisplayName = *data.GetDisplayName()
	}
	if data.GetSweepName() != nil {
		params.SweepID = *data.GetSweepName()
	}
	if data.GetProject() != nil {
		if data.GetProject().GetName() != "" {
			params.Project = data.GetProject().GetName()
		}
		entity := data.GetProject().GetEntity()
		if entity.GetName() != "" {
			params.Entity = entity.GetName()
		}
	}
	if data.GetHistoryLineCount() != nil {
		params.FileStreamOffset[filestream.HistoryChunk] = *data.GetHistoryLineCount()
	}

	// Get Config information
	config := data.GetConfig()
	if config == nil {
		return nil, errors.New("no config found in resume response")
	} else {
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
				"sender: updateConfig: got type %T for %s",
				x, *config,
			)
		}

		if params.Config == nil {
			params.Config = make(map[string]any)
		}
		for key, value := range cfg {
			valueDict, ok := value.(map[string]any)
			if !ok {
				return nil, fmt.Errorf("unexpected type %T for %s", value, key)
			} else if val, ok := valueDict["value"]; ok {
				params.Config[key] = val
			}
		}
	}

	return nil, nil
}

func (r RewindBranch) ApplyUpdates(src, dst *RunParams) {
}
