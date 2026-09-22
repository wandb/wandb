package leet

import (
	"encoding/json"
	"errors"
	"fmt"
	"os"
	"path/filepath"

	"github.com/wandb/wandb/core/internal/observability"
)

// dirStateName is the file in a wandb directory that remembers how it was
// last viewed.
const dirStateName = ".wandb-leet.json"

// filterState is a persisted filter: the applied pattern and, for glob
// matching, the mode. Regex is the default and is not written.
type filterState struct {
	Query string `json:"query"`
	Mode  string `json:"mode,omitempty"`
}

func filterStateOf(f *Filter) filterState {
	state := filterState{Query: f.Query()}
	if f.Mode() == FilterModeGlob {
		state.Mode = "glob"
	}
	return state
}

func (s filterState) mode() FilterMatchMode {
	if s.Mode == "glob" {
		return FilterModeGlob
	}
	return FilterModeRegex
}

// dirState remembers how a wandb directory was last viewed so the view is
// back in place the next time it is opened. Every change is saved.
type dirState struct {
	path   string
	logger *observability.CoreLogger

	Metrics       filterState `json:"metrics_filter,omitzero"`
	SystemMetrics filterState `json:"system_metrics_filter,omitzero"`
	Runs          filterState `json:"runs_filter,omitzero"`

	// SelectedRuns and PinnedRun are run directory names.
	SelectedRuns []string `json:"selected_runs,omitempty"`
	PinnedRun    string   `json:"pinned_run,omitempty"`

	// LatestRun is the newest run in the directory when the selection was
	// last saved. A newer run on the next open is new to the user.
	LatestRun string `json:"latest_run,omitempty"`
}

// loadDirState reads the state remembered for wandbDir.
//
// A missing file yields empty state. An empty wandbDir, as for remote
// runs, yields empty state that is never saved.
func loadDirState(wandbDir string, logger *observability.CoreLogger) *dirState {
	ds := &dirState{logger: logger}
	if wandbDir == "" {
		return ds
	}
	ds.path = filepath.Join(wandbDir, dirStateName)

	data, err := os.ReadFile(ds.path)
	if err == nil {
		err = json.Unmarshal(data, ds)
	}
	if err != nil && !errors.Is(err, os.ErrNotExist) {
		logger.Error(fmt.Sprintf("leet: ignoring %s: %v", ds.path, err))
	}
	return ds
}

// bind restores f from slot, applies it, and saves slot whenever f changes.
func (ds *dirState) bind(slot *filterState, f *Filter, apply func()) {
	f.restore(slot.Query, slot.mode())
	if apply != nil {
		apply()
	}
	f.onChange = func() {
		*slot = filterStateOf(f)
		ds.save()
	}
}

func (ds *dirState) save() {
	if ds.path == "" {
		return
	}

	data, err := json.MarshalIndent(ds, "", "  ")
	if err == nil {
		tmp := ds.path + ".tmp"
		if err = os.WriteFile(tmp, data, 0o644); err == nil {
			err = os.Rename(tmp, ds.path)
		}
	}
	if err != nil {
		ds.logger.Error(fmt.Sprintf("leet: failed to save %s: %v", ds.path, err))
	}
}
