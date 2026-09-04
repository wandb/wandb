package leet

import (
	"encoding/json"
	"errors"
	"fmt"
	"os"
	"path/filepath"

	"github.com/wandb/wandb/core/internal/observability"
)

// dirFiltersName is the file in a wandb directory that remembers the
// filters last used there.
const dirFiltersName = ".wandb-leet.json"

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

// dirFilters remembers the filters last used in a wandb directory so they
// are in place the next time it is opened. Every change is saved.
type dirFilters struct {
	path   string
	logger *observability.CoreLogger

	Metrics       filterState `json:"metrics_filter,omitzero"`
	SystemMetrics filterState `json:"system_metrics_filter,omitzero"`
	Runs          filterState `json:"runs_filter,omitzero"`
}

// loadDirFilters reads the filters remembered for wandbDir.
//
// A missing file yields empty filters. An empty wandbDir, as for remote
// runs, yields empty filters that are never saved.
func loadDirFilters(wandbDir string, logger *observability.CoreLogger) *dirFilters {
	df := &dirFilters{logger: logger}
	if wandbDir == "" {
		return df
	}
	df.path = filepath.Join(wandbDir, dirFiltersName)

	data, err := os.ReadFile(df.path)
	if err == nil {
		err = json.Unmarshal(data, df)
	}
	if err != nil && !errors.Is(err, os.ErrNotExist) {
		logger.Error(fmt.Sprintf("leet: ignoring %s: %v", df.path, err))
	}
	return df
}

// bind restores f from slot, applies it, and saves slot whenever f changes.
func (df *dirFilters) bind(slot *filterState, f *Filter, apply func()) {
	f.restore(slot.Query, slot.mode())
	if apply != nil {
		apply()
	}
	f.onChange = func() {
		*slot = filterStateOf(f)
		df.save()
	}
}

func (df *dirFilters) save() {
	if df.path == "" {
		return
	}

	data, err := json.MarshalIndent(df, "", "  ")
	if err == nil {
		tmp := df.path + ".tmp"
		if err = os.WriteFile(tmp, data, 0o644); err == nil {
			err = os.Rename(tmp, df.path)
		}
	}
	if err != nil {
		df.logger.Error(fmt.Sprintf("leet: failed to save %s: %v", df.path, err))
	}
}
