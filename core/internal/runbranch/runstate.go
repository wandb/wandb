package runbranch

import (
	"context"
	"time"

	"github.com/Khan/genqlient/graphql"
	"github.com/wandb/wandb/core/internal/filestream"
	"github.com/wandb/wandb/core/pkg/service"
)

type RunStateParams struct {
	RunID       string
	Project     string
	Entity      string
	DisplayName string
	StartTime   time.Time
	StorageID   string
	SweepID     string

	// run state fields based on response from the server
	startingStep int64
	runtime      int32

	Tags    []string
	Config  map[string]any
	summary map[string]any

	FileStreamOffset filestream.FileStreamOffsetMap
}

type State struct {
	RunStateParams
	ctx        context.Context
	client     graphql.Client
	Intialized bool
	Branching  *BranchingState
}

func NewRunState(
	ctx context.Context,
	client graphql.Client,
	resume string,
	rewind *service.RunMoment,
	fork *service.RunMoment,
) *State {

	return &State{
		ctx:    ctx,
		client: client,
		RunStateParams: RunStateParams{
			FileStreamOffset: make(filestream.FileStreamOffsetMap),
		},
		Branching: NewBranchingState(
			resume,
			rewind,
			fork,
		),
	}
}

func (r *State) UpdateState(params RunStateParams) {
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
	if params.runtime != 0 {
		r.runtime = params.runtime
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

func (r *State) ApplyBranchingUpdates() error {
	switch r.Branching.Type {
	case "resume":
		return r.updateStateResumeMode(r.Branching)
	case "rewind":
		return r.updateStateRewindMode(r.Branching)
	case "fork":
		return r.updateStateForkMode(r.Branching)
	default:
		return nil
	}
}

func (r *State) ApplyRunUpdate(run *service.RunRecord) {
	switch {
	case r.Branching.Type == "resume":
		r.updateRunResumeMode(run)
	case r.Branching.Type == "rewind":
		r.updateRunRewindMode(run)
	case r.Branching.Type == "fork":
		r.updateRunForkMode(run)
	default:
	}
	r.applyRunUpdate(run)
}

func (r *State) applyRunUpdate(run *service.RunRecord) {
	run.Entity = r.Entity
	run.Project = r.Project
	run.DisplayName = r.DisplayName
	run.RunId = r.RunID
	run.StorageId = r.StorageID
	run.SweepId = r.SweepID
}
