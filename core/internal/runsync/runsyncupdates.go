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
}

// UpdatesFromRequest constructs RunSyncUpdates from a sync init request.
func UpdatesFromRequest(request *spb.ServerInitSyncRequest) *RunSyncUpdates {
	u := &RunSyncUpdates{}

	if entity := request.GetNewEntity(); len(entity) > 0 {
		u.Entity = entity
	}
	if project := request.GetNewProject(); len(project) > 0 {
		u.Project = project
	}
	if runID := request.GetNewRunId(); len(runID) > 0 {
		u.RunID = runID
	}

	return u
}

// Modify updates a record with modifications requested for syncing.
func (u *RunSyncUpdates) Modify(record *spb.Record) {
	if u == nil {
		return
	}

	if run := record.GetRun(); run != nil {
		if len(u.Entity) > 0 {
			run.Entity = u.Entity
		}

		if len(u.Project) > 0 {
			run.Project = u.Project
		}

		if len(u.RunID) > 0 {
			run.RunId = u.RunID
		}
	}
}
