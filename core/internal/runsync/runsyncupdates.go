package runsync

import spb "github.com/wandb/wandb/core/pkg/service_go_proto"

// RunSyncUpdates contains the updates to apply to a run when syncing it.
//
// A nil value makes no updates.
type RunSyncUpdates struct {
	// Changes to where to upload the run.
	//
	// Empty strings indicate no update.
	Entity, Project, RunID string

	// JobType is the new job type for the run if it's not empty.
	JobType string
}

// UpdatesFromRequest constructs RunSyncUpdates from a sync init request.
func UpdatesFromRequest(request *spb.ServerInitSyncRequest) *RunSyncUpdates {
	return &RunSyncUpdates{
		Entity:  request.GetNewEntity(),
		Project: request.GetNewProject(),
		RunID:   request.GetNewRunId(),
		JobType: request.GetNewJobType(),
	}
}

// Modify updates a record with modifications requested for syncing.
func (u *RunSyncUpdates) Modify(record *spb.Record) {
	if u == nil {
		return
	}

	if run := record.GetRun(); run != nil {
		if u.Entity != "" {
			run.Entity = u.Entity
		}

		if u.Project != "" {
			run.Project = u.Project
		}

		if u.RunID != "" {
			run.RunId = u.RunID
		}

		if u.JobType != "" {
			run.JobType = u.JobType
		}
	}
}
