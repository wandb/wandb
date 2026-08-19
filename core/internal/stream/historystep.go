package stream

import (
	"fmt"
	"strconv"

	"github.com/wandb/wandb/core/internal/observability"
	"github.com/wandb/wandb/core/internal/runhandle"
	"github.com/wandb/wandb/core/internal/runsummary"
	"github.com/wandb/wandb/core/internal/settings"
	spb "github.com/wandb/wandb/core/pkg/service_go_proto"
)

// HistoryStepTrackerFactory constructs a HistoryStepTracker.
type HistoryStepTrackerFactory struct {
	Logger     *observability.CoreLogger
	Settings   *settings.Settings
	RunSummary *runsummary.RunSummary
	RunHandle  *runhandle.RunHandle
}

// HistoryStepTracker assigns monotonic _step values to history rows and
// updates the summary _step metric.
type HistoryStepTracker struct {
	logger     *observability.CoreLogger
	settings   *settings.Settings
	runSummary *runsummary.RunSummary
	runHandle  *runhandle.RunHandle

	// nextAutoStep is the next _step value to assign to history rows that don't
	// already contain one.
	nextAutoStep        int64
	autoStepInitialized bool
}

// New returns a tracker that owns history step assignment.
func (f *HistoryStepTrackerFactory) New() *HistoryStepTracker {
	return &HistoryStepTracker{
		logger:     f.Logger,
		settings:   f.Settings,
		runSummary: f.RunSummary,
		runHandle:  f.RunHandle,
	}
}

// SeedStartingStep sets the auto-step counter. Tests use this in place of a
// RunHandle.
func (t *HistoryStepTracker) SeedStartingStep(step int64) {
	t.nextAutoStep = step
	t.autoStepInitialized = true
}

// ApplyHistoryStep writes a monotonic _step onto record, updates run summary
// _step when the tracker owns it, and returns summary updates to stream
// (nil if none).
func (t *HistoryStepTracker) ApplyHistoryStep(
	record *spb.HistoryRecord,
) *runsummary.Updates {
	if t.settings.IsSharedMode() {
		return nil
	}

	t.initializeAutoStep()

	if item := explicitHistoryStepItem(record); item != nil {
		if step, ok := t.parseHistoryStep(item); ok {
			if step < t.nextAutoStep {
				t.logger.CaptureWarn(
					"historystep: history _step behind running step, renumbering to keep steps monotonic",
					"provided_step", step,
					"assigned_step", t.nextAutoStep,
				)
				item.ValueJson = strconv.FormatInt(t.nextAutoStep, 10)
				step = t.nextAutoStep
			}
			record.Step = &spb.HistoryStep{Num: step}
			t.advanceAutoStepPast(step)
			return t.updateSummaryStep(step)
		}
	}

	if record.GetStep() != nil {
		step := record.GetStep().GetNum()
		if step < t.nextAutoStep {
			t.logger.CaptureWarn(
				"historystep: history _step behind running step, renumbering to keep steps monotonic",
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
		return t.updateSummaryStep(step)
	}

	step := t.nextAutoStep
	record.Step = &spb.HistoryStep{Num: step}
	record.Item = append(record.Item, &spb.HistoryItem{
		NestedKey: []string{"_step"},
		ValueJson: strconv.FormatInt(step, 10),
	})
	t.nextAutoStep++
	return t.updateSummaryStep(step)
}

func (t *HistoryStepTracker) updateSummaryStep(step int64) *runsummary.Updates {
	if t.settings.IsEnableServerSideDerivedSummary() {
		return nil
	}

	updates := runsummary.FromProto(&spb.SummaryRecord{Update: []*spb.SummaryItem{{
		Key:       "_step",
		ValueJson: strconv.FormatInt(step, 10),
	}}})
	if err := updates.Apply(t.runSummary); err != nil {
		t.logger.CaptureError(
			"stream",
			fmt.Errorf("historystep: error updating summary step: %v", err))
		return nil
	}

	return updates
}

func (t *HistoryStepTracker) initializeAutoStep() {
	if t.autoStepInitialized {
		return
	}

	startingStep := int64(0)
	if t.runHandle != nil {
		if upserter, err := t.runHandle.Upserter(); err == nil {
			run := &spb.RunRecord{}
			upserter.FillRunRecord(run)
			startingStep = run.GetStartingStep()
		}
	}

	t.nextAutoStep = startingStep
	t.autoStepInitialized = true
}

func (t *HistoryStepTracker) advanceAutoStepPast(step int64) {
	if step >= t.nextAutoStep {
		t.nextAutoStep = step + 1
	}
}

func isStepItem(item *spb.HistoryItem) bool {
	if item.GetKey() == "_step" {
		return true
	}
	nestedKey := item.GetNestedKey()
	return len(nestedKey) == 1 && nestedKey[0] == "_step"
}

func explicitHistoryStepItem(record *spb.HistoryRecord) *spb.HistoryItem {
	for _, item := range record.GetItem() {
		if isStepItem(item) {
			return item
		}
	}
	return nil
}

func (t *HistoryStepTracker) parseHistoryStep(
	item *spb.HistoryItem,
) (int64, bool) {
	step, err := strconv.ParseInt(item.GetValueJson(), 10, 64)
	if err != nil {
		t.logger.CaptureWarn(
			"historystep: ignoring unparseable history _step value",
			"value", item.GetValueJson(),
		)
		return 0, false
	}
	return step, true
}
