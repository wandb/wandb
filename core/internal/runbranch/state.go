package runbranch

import (
	"context"
	"errors"
	"time"

	"github.com/Khan/genqlient/graphql"
	"github.com/wandb/simplejsonext"
	"github.com/wandb/wandb/core/internal/filestream"
	"github.com/wandb/wandb/core/pkg/service"
	"google.golang.org/protobuf/types/known/timestamppb"
)

type RunParams struct {
	RunID       string
	Project     string
	Entity      string
	DisplayName string
	StartTime   time.Time
	StorageID   string
	SweepID     string

	// run state fields based on response from the server
	StartingStep int64
	Runtime      int32

	Tags    []string
	Config  map[string]any
	Summary map[string]any

	Resumed bool

	FileStreamOffset filestream.FileStreamOffsetMap
}

func (r *RunParams) Proto() *service.RunRecord {

	proto := &service.RunRecord{}

	// update runID if it exists
	if r.RunID != "" {
		proto.RunId = r.RunID
	}

	// update Entity if it exists
	if r.Entity != "" {
		proto.Entity = r.Entity
	}

	// update Project if it exists
	if r.Project != "" {
		proto.Project = r.Project
	}

	// update DisplayName if it exists
	if r.DisplayName != "" {
		proto.DisplayName = r.DisplayName
	}

	// update StartTime if it exists
	if r.StartingStep != 0 {
		proto.StartingStep = r.StartingStep
	}

	// update Runtime if it exists
	if r.Runtime != 0 {
		proto.Runtime = r.Runtime
	}

	// update StorageID if it exists
	if r.StorageID != "" {
		proto.StorageId = r.StorageID
	}

	// update SweepID if it exists
	if r.SweepID != "" {
		proto.SweepId = r.SweepID
	}

	// update the config
	if len(r.Config) > 0 {
		config := service.ConfigRecord{}
		for key, value := range r.Config {
			valueJson, _ := simplejsonext.MarshalToString(value)
			config.Update = append(config.Update, &service.ConfigItem{
				Key:       key,
				ValueJson: valueJson,
			})
		}
		proto.Config = &config
	}

	// update the summary
	if len(r.Summary) > 0 {
		summary := service.SummaryRecord{}
		for key, value := range r.Summary {
			valueJson, _ := simplejsonext.MarshalToString(value)
			summary.Update = append(summary.Update, &service.SummaryItem{
				Key:       key,
				ValueJson: valueJson,
			})
		}
		proto.Summary = &summary
	}

	if !r.StartTime.IsZero() {
		proto.StartTime = timestamppb.New(r.StartTime)
	}

	return proto
}

type State struct {
	RunParams
	Intialized bool
	branch     Branching
}

func NewState(
	ctx context.Context,
	client graphql.Client,
	resume string,
	rewind *service.RunMoment,
	fork *service.RunMoment,
) *State {

	state := &State{
		RunParams: RunParams{
			FileStreamOffset: make(filestream.FileStreamOffsetMap),
		},
	}

	switch {
	case resume != "" && rewind != nil || resume != "" && fork != nil || rewind != nil && fork != nil:
		state.branch = &InvalidBranch{
			err: errors.New("provide only one of resume, rewind or fork"),
			response: &service.ErrorInfo{
				Code:    service.ErrorInfo_USAGE,
				Message: "provide only one of resume, rewind or fork",
			},
		}
	case resume != "":
		state.branch = &ResumeBranch{
			ctx:    ctx,
			client: client,
			mode:   resume,
		}
	case rewind != nil:
		state.branch = &RewindBranch{
			runid:  rewind.GetRun(),
			metric: rewind.GetMetric(),
			value:  rewind.GetValue(),
		}
	case fork != nil:
		state.branch = &ForkBranch{
			runid:  fork.GetRun(),
			metric: fork.GetMetric(),
			value:  fork.GetValue(),
		}
	default:
		state.branch = &NoBranch{}
	}
	return state
}

func (r *State) ApplyBranchUpdates() error {
	update, err := r.branch.GetUpdates(
		RunPath{
			Entity:  r.Entity,
			Project: r.Project,
			RunID:   r.RunID,
		})
	if err != nil {
		return err
	}
	r.branch.ApplyUpdates(update, &r.RunParams)
	return nil
}

func (r *State) ApplyRunRecordUpdates(params *RunParams) {
	r.RunParams.RunID = params.RunID
	r.RunParams.Entity = params.Entity
	r.RunParams.Project = params.Project
	r.RunParams.DisplayName = params.DisplayName
	r.RunParams.StartTime = params.StartTime
	r.RunParams.StorageID = params.StorageID
	r.RunParams.SweepID = params.SweepID
}

func (r *State) ApplyUpsertUpdates(params *RunParams) {
	r.RunParams.RunID = params.RunID
	r.RunParams.Entity = params.Entity
	r.RunParams.Project = params.Project
	r.RunParams.DisplayName = params.DisplayName
	r.RunParams.StorageID = params.StorageID
	r.RunParams.SweepID = params.SweepID
}
