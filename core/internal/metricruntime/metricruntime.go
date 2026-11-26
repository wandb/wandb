// Package metricruntime deals with the "_runtime" metric.
//
// The "_runtime" metric is displayed like "Relative Time (Process)" in the UI.
// It is the default X axis for system metrics. Every history step has an
// associated `_runtime`, and it is present in the summary regardless of
// whether there are any history steps.
//
// In the summary, both "_wandb.runtime" and "_runtime" are used.
// This is an unfinished refactor from times past. The "_wandb.runtime"
// form is generally prioritized, and the "_runtime" form could one day
// be removed.
package metricruntime

import (
	"time"

	"github.com/wandb/wandb/core/internal/pathtree"
	"github.com/wandb/wandb/core/internal/runhistory"
	"github.com/wandb/wandb/core/internal/runsummary"

	spb "github.com/wandb/wandb/core/pkg/service_go_proto"
)

var (
	runtimeKey      = pathtree.PathOf("_runtime")
	wandbRuntimeKey = pathtree.PathOf("_wandb", "runtime")
)

// FromHistoryRecord returns the value of the _runtime metric
// in a history record.
//
// The `history` object is expected to have been constructed from the `record`.
// The `startRuntime` is this run segment's initial runtime.
func FromHistoryRecord(
	startRuntime time.Duration,
	history *runhistory.RunHistory,
	record *spb.HistoryRecord,
) time.Duration {
	// Older SDKs set _runtime on history.
	if record.RelativeTimeMs == nil {
		runtime, _ := history.GetNumber(runtimeKey)
		return time.Duration(runtime*1000) * time.Millisecond
	}

	return fromRelativeTimeMs(startRuntime, *record.RelativeTimeMs)
}

// FromExitRecord returns the value of _runtime metric in an exit record.
//
// The `startRuntime` is this run segment's initial runtime.
func FromExitRecord(
	startRuntime time.Duration,
	record *spb.RunExitRecord,
) time.Duration {
	// Older SDKs set the runtime field.
	if record.RelativeTimeMs == nil {
		return time.Duration(record.Runtime) * time.Second
	}

	return fromRelativeTimeMs(startRuntime, *record.RelativeTimeMs)
}

// fromRelativeTimeMs turns a `relative_time_ms` value into a runtime.
func fromRelativeTimeMs(
	startRuntime time.Duration,
	relativeTimeMs int64,
) time.Duration {
	relativeTime := time.Duration(relativeTimeMs) * time.Millisecond
	return startRuntime + relativeTime
}

// SetInHistory sets the history value of the runtime metric.
func SetInHistory(history *runhistory.RunHistory, runtime time.Duration) {
	history.SetFloat(runtimeKey, runtime.Seconds())
}

// SetInSummary sets the summary of the runtime metric to the given value.
//
// For convenience and a fluent API, this returns the updates instance.
func SetInSummary(
	updates *runsummary.Updates,
	runtime time.Duration,
) *runsummary.Updates {
	return updates.
		Set(runtimeKey, runtime.Seconds()).
		Set(wandbRuntimeKey, runtime.Seconds())
}

// IgnoreInSummary removes runtime metric updates from the summary.
func IgnoreInSummary(updates *runsummary.Updates) {
	updates.Ignore(runtimeKey)
	updates.Ignore(wandbRuntimeKey)
}
