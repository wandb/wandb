package runresume

import (
	"context"

	"github.com/Khan/genqlient/graphql"
	"github.com/wandb/wandb/core/internal/filestream"
	"github.com/wandb/wandb/core/pkg/service"
)

type RunState struct {
	ctx     context.Context
	client  graphql.Client
	Started bool

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
	runID string,
	project string,
	entity string,
	tags []string,
	started bool,
) *RunState {
	return &RunState{
		ctx:              ctx,
		client:           client,
		FileStreamOffset: make(filestream.FileStreamOffsetMap),
		RunID:            runID,
		Project:          project,
		Entity:           entity,
		Tags:             tags,
		Started:          started,
	}
}

func (r *RunState) Update(settings *service.Settings) (*service.ErrorInfo, error) {
	switch {
	case settings.GetResume().GetValue() != "":
		return r.UpdateResume(settings.GetResume().GetValue())
	case settings.ResumeFrom != nil:
		return nil, r.UpdateRewind()
	case settings.ForkFrom != nil:
		return nil, nil
	default:
		return nil, nil
	}
}

func (r *RunState) Apply(settings *service.Settings, record *service.RunRecord) {
	if settings.GetResume().GetValue() != "" {
		r.ApplyResume(record)
	}
	r.ApplyUpsert(record)
}

func (r *RunState) ApplyUpsert(record *service.RunRecord) {
	record.RunId = r.RunID
	record.Project = r.Project
	record.Entity = r.Entity
	record.DisplayName = r.DisplayName
	record.SweepId = r.SweepID
	record.StorageId = r.StorageID
}
