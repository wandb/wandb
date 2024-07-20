package runbranch

import (
	"context"
	"errors"
	"time"

	"github.com/Khan/genqlient/graphql"
	"github.com/wandb/simplejsonext"
	"github.com/wandb/wandb/core/internal/filestream"
	"github.com/wandb/wandb/core/pkg/service"
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
	startingStep int64
	Runtime      int32

	Tags    []string
	Config  map[string]any
	summary map[string]any

	Resumed bool

	FileStreamOffset filestream.FileStreamOffsetMap
}

func (r *RunParams) Update(params *RunParams) {
	if params == nil {
		return
	}

	if params.RunID != "" {
		r.RunID = params.RunID
	}
	if params.Project != "" {
		r.Project = params.Project
	}
	if params.Entity != "" {
		r.Entity = params.Entity
	}
	if params.DisplayName != "" {
		r.DisplayName = params.DisplayName
	}
	if params.SweepID != "" {
		r.SweepID = params.SweepID
	}
	if params.StorageID != "" {
		r.StorageID = params.StorageID
	}
	if !params.StartTime.IsZero() {
		r.StartTime = params.StartTime
	}
	if params.startingStep != 0 {
		r.startingStep = params.startingStep
	}
	if params.Runtime != 0 {
		r.Runtime = params.Runtime
	}
	if len(params.Tags) > 0 {
		r.Tags = params.Tags
	}
	if len(params.Config) > 0 {
		r.Config = params.Config
	}
	if len(params.summary) > 0 {
		r.summary = params.summary
	}
	if len(params.FileStreamOffset) > 0 {
		r.FileStreamOffset = params.FileStreamOffset
	}
}

func (r *RunParams) Proto() *service.RunRecord {

	// // update the config
	// config := service.ConfigRecord{}
	// for key, value := range r.Config {
	// 	valueJson, _ := simplejsonext.MarshalToString(value)
	// 	config.Update = append(config.Update, &service.ConfigItem{
	// 		Key:       key,
	// 		ValueJson: valueJson,
	// 	})
	// }
	// run.Config = &config

	// update the summary
	summary := service.SummaryRecord{}
	for key, value := range r.summary {
		valueJson, _ := simplejsonext.MarshalToString(value)
		summary.Update = append(summary.Update, &service.SummaryItem{
			Key:       key,
			ValueJson: valueJson,
		})
	}
	return &service.RunRecord{
		RunId:        r.RunID,
		Project:      r.Project,
		Entity:       r.Entity,
		DisplayName:  r.DisplayName,
		StartingStep: r.startingStep,
		StorageId:    r.StorageID,
		SweepId:      r.SweepID,
		Summary:      &summary,
	}
}

type State struct {
	RunParams
	ctx        context.Context
	client     graphql.Client
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
		ctx:    ctx,
		client: client,
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
			mode: resume,
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

func (r *State) ApplyUpdates(params *RunParams) error {
	r.RunParams.Update(params)
	update, err := r.branch.GetUpdates(r.ctx, r.client, r.Entity, r.Project, r.RunID)
	if err != nil {
		return err
	}
	r.RunParams.Update(update)
	return nil
}
