package runresume

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

type RunState struct {
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
	step    int64
	runtime int32

	Tags    []string
	Config  map[string]any
	summary map[string]any

	FileStreamOffset filestream.FileStreamOffsetMap

	Branching BranchingState
}

type BranchingState struct {
	RunID     string
	StepName  string
	StepValue float64
	Mode      string
	Type      string
}

func NewRunState(
	ctx context.Context,
	client graphql.Client,
	resume string,
	rewind *service.RunMoment,
	fork *service.RunMoment,
) *RunState {

	var branching BranchingState
	switch {
	case resume != "":
		branching = BranchingState{
			Mode: resume,
			Type: "resume",
		}
	case rewind != nil:
		branching = BranchingState{
			RunID:     rewind.GetRun(),
			StepName:  rewind.GetMetric(),
			StepValue: rewind.GetValue(),
			Type:      "rewind",
		}
	case fork != nil:
		branching = BranchingState{
			RunID:     fork.GetRun(),
			StepName:  fork.GetMetric(),
			StepValue: fork.GetValue(),
			Type:      "fork",
		}
	default:
		branching = BranchingState{
			Type: "none",
		}
	}

	return &RunState{
		ctx:              ctx,
		client:           client,
		FileStreamOffset: make(filestream.FileStreamOffsetMap),
		Branching:        branching,
	}
}

func (r *RunState) ApplyBranchingUpdates() (*service.ErrorInfo, error) {
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

func (r *RunState) UpdateState(params RunStateParams) {
	r.RunID = params.RunID
	r.Project = params.Project
	r.Entity = params.Entity
	r.DisplayName = params.DisplayName
	r.SweepID = params.SweepID
	r.StorageID = params.StorageID
	r.startTimeSecs = params.StartTimeSecs
	r.startTimeNanos = params.StartTimeNanos
}

func (r *RunState) ApplyRunUpdate(run *service.RunRecord) {
	switch {
	case r.Branching.Mode == "resume":
		r.updateRunResumeMode(run)
	case r.Branching.Mode == "rewind":
		r.updateRunRewindMode(run)
	case r.Branching.Mode == "fork":
		// r.applyFork(record)
	default:
	}
}
