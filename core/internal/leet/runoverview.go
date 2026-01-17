package leet

import (
	"fmt"
	"slices"
	"sort"

	"github.com/wandb/wandb/core/internal/runconfig"
	"github.com/wandb/wandb/core/internal/runenvironment"
	"github.com/wandb/wandb/core/internal/runsummary"
	spb "github.com/wandb/wandb/core/pkg/service_go_proto"
)

const runOverviewHeader = "Run Overview"

// RunState indicates the current state of the run.
type RunState int32

const (
	RunStateUnknown RunState = iota
	RunStateRunning
	RunStateFinished
	RunStateFailed
	RunStateCrashed
)

// KeyValuePair represents a single key-value item to display.
type KeyValuePair struct {
	Key, Value string

	// Path is the full path for nested items.
	Path []string
}

// RunOverview processes and stores run metadata.
type RunOverview struct {
	runID          string
	displayName    string
	project        string
	runConfig      *runconfig.RunConfig
	runEnvironment *runenvironment.RunEnvironment
	runSummary     *runsummary.RunSummary
	runState       RunState
}

func NewRunOverview() *RunOverview {
	return &RunOverview{
		runConfig:  runconfig.New(),
		runSummary: runsummary.New(),
	}
}

// StateString returns a string representation from the data model.
func (ro *RunOverview) StateString() string {
	switch ro.State() {
	case RunStateRunning:
		return "Running"
	case RunStateFinished:
		return "Finished"
	case RunStateFailed:
		return "Failed"
	case RunStateCrashed:
		return "Error"
	default:
		return "Unknown"
	}
}

// ProcessRunMsg processes a run message and updates internal state.
func (ro *RunOverview) ProcessRunMsg(msg RunMsg) {
	ro.runID = msg.ID
	ro.displayName = msg.DisplayName
	ro.project = msg.Project
	ro.runState = RunStateRunning

	if msg.Config != nil {
		ro.runConfig.ApplyChangeRecord(msg.Config, func(err error) {})
	}
}

// ProcessSystemInfoMsg processes system/environment information.
func (ro *RunOverview) ProcessSystemInfoMsg(record *spb.EnvironmentRecord) {
	if ro.runEnvironment == nil && record != nil {
		ro.runEnvironment = runenvironment.New(record.GetWriterId())
	}
	if ro.runEnvironment != nil {
		ro.runEnvironment.ProcessRecord(record)
	}
}

// ProcessSummaryMsg processes summary data.
func (ro *RunOverview) ProcessSummaryMsg(summary []*spb.SummaryRecord) {
	for _, s := range summary {
		_ = runsummary.FromProto(s).Apply(ro.runSummary)
	}

}

// SetRunState sets the run state.
func (ro *RunOverview) SetRunState(state RunState) {
	ro.runState = state
}

// Data accessors

// ID returns the run ID.
func (ro *RunOverview) ID() string {
	return ro.runID
}

// DisplayName returns the run display name.
func (ro *RunOverview) DisplayName() string {
	return ro.displayName
}

// Project returns the project name.
func (ro *RunOverview) Project() string {
	return ro.project
}

// State returns the run state.
func (ro *RunOverview) State() RunState {
	return ro.runState
}

// EnvironmentItems returns environment data as key-value pairs.
func (ro *RunOverview) EnvironmentItems() []KeyValuePair {
	if ro.runEnvironment == nil {
		return []KeyValuePair{}
	}

	envData := ro.runEnvironment.ToRunConfigData()
	return processEnvironmentData(envData)
}

// ConfigItems returns config data as key-value pairs.
func (ro *RunOverview) ConfigItems() []KeyValuePair {
	if ro.runConfig == nil {
		return []KeyValuePair{}
	}

	items := make([]KeyValuePair, 0)
	flattenMap(ro.runConfig.CloneTree(), "", &items, []string{})
	return items
}

// SummaryItems returns summary data as key-value pairs.
func (ro *RunOverview) SummaryItems() []KeyValuePair {
	if ro.runSummary == nil {
		return []KeyValuePair{}
	}

	items := make([]KeyValuePair, 0)
	flattenMap(ro.runSummary.ToNestedMaps(), "", &items, []string{})
	return items
}

// flattenMap converts nested maps to flat key-value pairs.
//
// - Map keys are sorted (deterministic).
// - Slices are flattened using bracketed indices (e.g., a[0].b).
func flattenMap(data map[string]any, prefix string, result *[]KeyValuePair, path []string) {
	if data == nil {
		return
	}

	keys := make([]string, 0, len(data))
	for k := range data {
		keys = append(keys, k)
	}
	sort.Strings(keys)

	for _, k := range keys {
		v := data[k]

		fullKey := k
		if prefix != "" {
			fullKey = prefix + "." + k
		}
		currentPath := slices.Concat(path, []string{k})

		switch val := v.(type) {
		case map[string]any:
			flattenMap(val, fullKey, result, currentPath)
		case []any:
			flattenSlice(val, fullKey, result, currentPath)
		default:
			*result = append(*result, KeyValuePair{
				Key:   fullKey,
				Value: fmt.Sprint(v),
				Path:  currentPath,
			})
		}
	}
}

// flattenSlice handles []any by emitting `prefix[i]` and recursing as needed.
func flattenSlice(list []any, prefix string, result *[]KeyValuePair, path []string) {
	for i, elem := range list {
		idxFrag := fmt.Sprintf("[%d]", i)
		fullKey := prefix + idxFrag
		idxPath := slices.Concat(path, []string{idxFrag})

		switch e := elem.(type) {
		case map[string]any:
			flattenMap(e, fullKey, result, idxPath)
		case []any:
			flattenSlice(e, fullKey, result, idxPath)
		default:
			*result = append(*result, KeyValuePair{
				Key:   fullKey,
				Value: fmt.Sprint(e),
				Path:  idxPath,
			})
		}
	}
}

// processEnvironmentData handles special processing for environment data.
//
// The run's transaction log should only contain info about a single writer.
func processEnvironmentData(data map[string]any) []KeyValuePair {
	if data == nil {
		return []KeyValuePair{}
	}

	keys := make([]string, 0, len(data))
	for k := range data {
		keys = append(keys, k)
	}

	if len(keys) == 0 {
		return []KeyValuePair{}
	}

	sort.Strings(keys)
	firstKey := keys[0]

	firstValue, ok := data[firstKey]
	if !ok {
		return []KeyValuePair{}
	}

	if valueMap, ok := firstValue.(map[string]any); ok {
		result := make([]KeyValuePair, 0)
		flattenMap(valueMap, "", &result, []string{})
		return result
	}

	return []KeyValuePair{
		{Key: firstKey, Value: fmt.Sprintf("%v", firstValue), Path: []string{firstKey}},
	}
}
