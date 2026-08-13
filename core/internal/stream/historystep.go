package stream

import (
	"fmt"
	"strconv"

	"github.com/wandb/wandb/core/internal/observability"
	"github.com/wandb/wandb/core/internal/runsummary"
	"github.com/wandb/wandb/core/internal/settings"
	spb "github.com/wandb/wandb/core/pkg/service_go_proto"
)

// HistoryStepTrackerParams are the dependencies for a HistoryStepTracker.
type HistoryStepTrackerParams struct {
	Logger     *observability.CoreLogger
	Settings   *settings.Settings
	RunSummary *runsummary.RunSummary
}

// HistoryStepTracker assigns monotonic _step values to history rows and
// materializes the summary _step metric.
type HistoryStepTracker struct {
	logger     *observability.CoreLogger
	settings   *settings.Settings
	runSummary *runsummary.RunSummary

	// nextAutoStep is the next _step value to assign to history rows that don't
	// already contain one.
	nextAutoStep        int64
	autoStepInitialized bool
}

// NewHistoryStepTracker returns a tracker that owns history step assignment.
func NewHistoryStepTracker(p HistoryStepTrackerParams) *HistoryStepTracker {
	return &HistoryStepTracker{
		logger:     p.Logger,
		settings:   p.Settings,
		runSummary: p.RunSummary,
	}
}

// Process ensures the history row has a monotonic _step, updates the run
// summary _step when appropriate, and returns summary updates for the
// filestream (nil when nothing should be streamed).
//
// startingStep seeds the auto-step counter on the first call (typically from
// RunRecord.StartingStep). Later calls ignore the value.
func (t *HistoryStepTracker) Process(
	record *spb.HistoryRecord,
	startingStep int64,
) *runsummary.Updates {
	t.ensureHistoryStep(record, startingStep)
	return t.materializeSummaryStep(record)
}

// ensureHistoryStep adds _step to history rows that do not already have it.
//
// Existing _step values are preserved unless they fall behind the tracker's
// running step counter, which would break the monotonic ordering the
// filestream requires. In this case the value is clamped to the running step
// counter, the original user-provided step is dropped, and a warning is
// logged.
func (t *HistoryStepTracker) ensureHistoryStep(
	record *spb.HistoryRecord,
	startingStep int64,
) {
	if record == nil {
		return
	}
	if t.settings.IsSharedMode() {
		return
	}

	if step, ok := t.explicitHistoryStepItem(record); ok {
		t.initializeAutoStep(startingStep)
		if step < t.nextAutoStep {
			t.logger.CaptureWarn(
				"sender: history _step behind running step, renumbering to keep steps monotonic",
				"provided_step", step,
				"assigned_step", t.nextAutoStep,
			)
			setExplicitHistoryStep(record, t.nextAutoStep)
			step = t.nextAutoStep
		}
		record.Step = &spb.HistoryStep{Num: step}
		t.advanceAutoStepPast(step)
		return
	}

	if record.GetStep() != nil {
		t.initializeAutoStep(startingStep)
		step := record.GetStep().GetNum()
		if step < t.nextAutoStep {
			t.logger.CaptureWarn(
				"sender: history _step behind running step, renumbering to keep steps monotonic",
				"provided_step", step,
				"assigned_step", t.nextAutoStep,
			)
			record.Step.Num = t.nextAutoStep
			step = t.nextAutoStep
		}
		record.Item = append(record.Item, &spb.HistoryItem{
			NestedKey: []string{"_step"},
			ValueJson: strconv.FormatInt(step, 10),
		})
		t.advanceAutoStepPast(step)
		return
	}

	t.initializeAutoStep(startingStep)

	step := t.nextAutoStep
	record.Step = &spb.HistoryStep{Num: step}
	record.Item = append(record.Item, &spb.HistoryItem{
		NestedKey: []string{"_step"},
		ValueJson: strconv.FormatInt(step, 10),
	})
	t.nextAutoStep++
}

// materializeSummaryStep updates the run summary _step metric, if the tracker
// is not in shared mode and server-side summary derivation is not enabled.
// It returns the updates to stream, or nil when nothing should be streamed.
func (t *HistoryStepTracker) materializeSummaryStep(
	record *spb.HistoryRecord,
) *runsummary.Updates {
	if record == nil {
		return nil
	}
	if t.settings.IsSharedMode() || t.settings.IsEnableServerSideDerivedSummary() {
		return nil
	}
	if record.GetStep() == nil {
		return nil
	}

	updates := runsummary.FromProto(&spb.SummaryRecord{Update: []*spb.SummaryItem{{
		Key:       "_step",
		ValueJson: strconv.FormatInt(record.GetStep().GetNum(), 10),
	}}})
	if err := updates.Apply(t.runSummary); err != nil {
		t.logger.CaptureError(
			"stream",
			fmt.Errorf("stream: error updating summary step: %v", err))
		return nil
	}

	return updates
}

// StripSummaryStep removes _step from an inbound summary record if necessary.
//
// Summary _step should only be set by the HistoryStepTracker. If it was set
// in a transaction log by an older wandb version, it is overwritten here.
// In shared mode or server-side summary derivation is enabled, the summary _step
// is not stripped.
func (t *HistoryStepTracker) StripSummaryStep(
	summary *spb.SummaryRecord,
) *spb.SummaryRecord {
	// Only strip a _step we would go on to replace.
	if t.settings.IsSharedMode() || t.settings.IsEnableServerSideDerivedSummary() {
		return summary
	}

	updates := summary.GetUpdate()
	kept := make([]*spb.SummaryItem, 0, len(updates))
	for _, item := range updates {
		if !isStepItem(item) {
			kept = append(kept, item)
		}
	}

	if len(kept) == len(updates) {
		return summary
	}

	// Shallow copy: the caller's record is also headed for the Writer.
	return &spb.SummaryRecord{
		Update: kept,
		Remove: summary.GetRemove(),
	}
}

func (t *HistoryStepTracker) initializeAutoStep(startingStep int64) {
	if t.autoStepInitialized {
		return
	}

	t.nextAutoStep = startingStep
	t.autoStepInitialized = true
}

func (t *HistoryStepTracker) advanceAutoStepPast(step int64) {
	if step >= t.nextAutoStep {
		t.nextAutoStep = step + 1
	}
}

// stepKeyed is satisfied by both *spb.HistoryItem and *spb.SummaryItem, which
// each expose a flat key plus an optional nested-key path.
type stepKeyed interface {
	GetKey() string
	GetNestedKey() []string
}

// isStepItem reports whether item is the reserved "_step" key, whether it is
// written as a flat key or a single-element nested key.
func isStepItem(item stepKeyed) bool {
	if item.GetKey() == "_step" {
		return true
	}
	nestedKey := item.GetNestedKey()
	return len(nestedKey) == 1 && nestedKey[0] == "_step"
}

func (t *HistoryStepTracker) explicitHistoryStepItem(
	record *spb.HistoryRecord,
) (int64, bool) {
	for _, item := range record.GetItem() {
		if !isStepItem(item) {
			continue
		}

		step, err := strconv.ParseInt(item.GetValueJson(), 10, 64)
		if err != nil {
			t.logger.CaptureWarn(
				"sender: ignoring unparseable history _step value",
				"value", item.GetValueJson(),
			)
			return 0, false
		}
		return step, true
	}

	return 0, false
}

func setExplicitHistoryStep(record *spb.HistoryRecord, step int64) {
	stepStr := strconv.FormatInt(step, 10)
	for _, item := range record.GetItem() {
		if isStepItem(item) {
			item.ValueJson = stepStr
			return
		}
	}

	record.Item = append(record.Item, &spb.HistoryItem{
		NestedKey: []string{"_step"},
		ValueJson: stepStr,
	})
}
