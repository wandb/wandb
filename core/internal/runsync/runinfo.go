package runsync

import (
	"errors"
	"net/url"
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

	if len(info.Entity) > 0 {
		parts = append(parts, info.Entity)
	}
	if len(info.Project) > 0 {
		parts = append(parts, info.Project)
	}

	if len(info.RunID) > 0 {
		parts = append(parts, info.RunID)
	} else {
		// Not normally valid, but useful for debugging.
		parts = append(parts, "<no ID>")
	}

	// NOTE: The components never contain forward slashes.
	return strings.Join(parts, "/")
}

// URL returns the run's URL given the URL for the W&B web UI.
//
// If the run's entity or project is not known, this returns an error.
func (info *RunInfo) URL(appURL string) (string, error) {
	switch {
	case len(info.Entity) == 0:
		return "", errors.New("no entity")
	case len(info.Project) == 0:
		return "", errors.New("no project")
	case len(info.RunID) == 0:
		return "", errors.New("no run ID")
	}

	entity := url.PathEscape(info.Entity)
	project := url.PathEscape(info.Project)
	runID := url.PathEscape(info.RunID)

	return url.JoinPath(appURL, entity, project, "runs", runID)
}
