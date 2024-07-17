package runresume

import (
	"context"

	"github.com/Khan/genqlient/graphql"
	"github.com/wandb/wandb/core/internal/filestream"
	"github.com/wandb/wandb/core/pkg/service"
)

type RunState struct {
	ctx        context.Context
	client     graphql.Client
	Intialized bool

	RunID       string
	Project     string
	Entity      string
	DisplayName string
	StartTime   int64

	// run state fields based on response from the server
	step      int64
	runtime   int32
	Tags      []string
	Config    map[string]any
	summary   map[string]any
	StorageID string
	SweepID   string

	FileStreamOffset filestream.FileStreamOffsetMap
}

func NewRunState(
	ctx context.Context,
	client graphql.Client,
) *RunState {
	return &RunState{
		ctx:              ctx,
		client:           client,
		FileStreamOffset: make(filestream.FileStreamOffsetMap),
	}
}

func (r *RunState) Update(settings *service.Settings, record *service.RunRecord) (*service.ErrorInfo, error) {
	r.updateUpsert(record)
	switch {
	case settings.GetResume().GetValue() != "":
		return r.updateResume(settings.GetResume().GetValue())
	case settings.ResumeFrom != nil:
		return nil, r.UpdateRewind()
	case settings.ForkFrom != nil:
		return nil, nil
	default:
		return nil, nil
	}
}

func (r *RunState) updateUpsert(record *service.RunRecord) {
	record.RunId = r.RunID
	record.Project = r.Project
	record.Entity = r.Entity
	record.DisplayName = r.DisplayName
	record.SweepId = r.SweepID
	record.StorageId = r.StorageID
}

func (r *RunState) Apply(settings *service.Settings, record *service.RunRecord) {
	switch {
	case settings.GetResume().GetValue() != "":
		r.applyResume(record)
	case settings.ResumeFrom != nil:
		r.applyRewind(record)
	case settings.ForkFrom != nil:
		// r.applyFork(record)
	default:
	}
	r.applyUpsert(record)
}

func (r *RunState) applyUpsert(record *service.RunRecord) {
	record.RunId = r.RunID
	record.Project = r.Project
	record.Entity = r.Entity
	record.DisplayName = r.DisplayName
	record.SweepId = r.SweepID
	record.StorageId = r.StorageID
}
