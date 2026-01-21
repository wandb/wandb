package runsync

import (
	"strings"
	"time"
)

// RunInfo is basic information about a run that can be extracted from
// its transaction log.
type RunInfo struct {
	// Components of the run's path.
	//
	// Entity and Project may be empty to indicate that the user's defaults
	// should be used.
	Entity, Project, RunID string

	// StartTime is the time this run instance was initialized.
	StartTime time.Time
}

// Path returns the run's full path in the form entity/project/id
// with empty values omitted.
func (info *RunInfo) Path() string {
	parts := make([]string, 0, 3)

	if info.Entity != "" {
		parts = append(parts, info.Entity)
	}
	if info.Project != "" {
		parts = append(parts, info.Project)
	}

	if info.RunID != "" {
		parts = append(parts, info.RunID)
	} else {
		// Not normally valid, but useful for debugging.
		parts = append(parts, "<no ID>")
	}

	// NOTE: The components never contain forward slashes.
	return strings.Join(parts, "/")
}
