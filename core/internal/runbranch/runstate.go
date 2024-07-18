package runbranch

import (
	"context"

	"github.com/Khan/genqlient/graphql"
	"github.com/wandb/wandb/core/internal/filestream"
	"github.com/wandb/wandb/core/pkg/service"
)

type RunStateParams struct {
	RunID          string
	Project        string
	Entity         string
	DisplayName    string
	StartTimeSecs  int64
	StartTimeNanos int32
	StorageID      string
	SweepID        string
}

type State struct {
	ctx        context.Context
	client     graphql.Client
	Intialized bool

	RunID          string
	Project        string
	Entity         string
	DisplayName    string
	startTimeSecs  int64
	startTimeNanos int32
	StorageID      string
	SweepID        string

	// run state fields based on response from the server
	startingStep int64
	runtime      int32

	Tags    []string
	Config  map[string]any
	summary map[string]any

	FileStreamOffset filestream.FileStreamOffsetMap

	Branching *BranchingState
}

func NewRunState(
	ctx context.Context,
	client graphql.Client,
	resume string,
	rewind *service.RunMoment,
	fork *service.RunMoment,
) *State {

	return &State{
		ctx:              ctx,
		client:           client,
		FileStreamOffset: make(filestream.FileStreamOffsetMap),
		Branching: NewBranchingState(
			resume,
			rewind,
			fork,
		),
	}
}

func (r *State) UpdateState(params RunStateParams) {
	r.RunID = params.RunID
	r.Project = params.Project
	r.Entity = params.Entity
	r.DisplayName = params.DisplayName
	r.SweepID = params.SweepID
	r.StorageID = params.StorageID
	r.startTimeSecs = params.StartTimeSecs
	r.startTimeNanos = params.StartTimeNanos
}

func (r *State) ApplyBranchingUpdates() (*service.ErrorInfo, error) {
	switch r.Branching.Type {
	case "resume":
		return r.updateStateResumeMode(r.Branching)
	case "rewind":
		return r.updateStateRewindMode(r.Branching)
	case "fork":
		return r.updateStateForkMode(r.Branching)
	default:
		return nil, nil
	}
}

func (r *State) ApplyRunUpdate(run *service.RunRecord) {
	switch {
	case r.Branching.Mode == "resume":
		r.updateRunResumeMode(run)
	case r.Branching.Mode == "rewind":
		r.updateRunRewindMode(run)
	case r.Branching.Mode == "fork":
		r.updateRunForkMode(run)
	default:
	}
}
