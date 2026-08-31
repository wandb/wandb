package stream

import (
	"fmt"
	"strconv"

	"github.com/wandb/wandb/core/internal/observability"
	"github.com/wandb/wandb/core/internal/runhandle"
	"github.com/wandb/wandb/core/internal/settings"
	spb "github.com/wandb/wandb/core/pkg/service_go_proto"
)

// HistoryStepTrackerFactory constructs a HistoryStepTracker.
type HistoryStepTrackerFactory struct {
	Logger    *observability.CoreLogger
	Settings  *settings.Settings
	RunHandle *runhandle.RunHandle
}

// HistoryStepTracker assigns increasing _step values to history rows.
type HistoryStepTracker struct {
	logger    *observability.CoreLogger
	settings  *settings.Settings
	runHandle *runhandle.RunHandle

	// nextStep is the minimum step for the next history row.
	nextStep    int64
	initialized bool
}

// New returns a tracker that owns history step assignment.
func (f *HistoryStepTrackerFactory) New() *HistoryStepTracker {
	return &HistoryStepTracker{
		logger:    f.Logger,
		settings:  f.Settings,
		runHandle: f.RunHandle,
	}
}

// ApplyHistoryStep writes an increasing _step onto record.
//
// In shared mode it leaves the record unchanged and returns 0, nil.
// err is non-nil when the run is not initialized; the caller must skip
// the history row.
func (t *HistoryStepTracker) ApplyHistoryStep(
	record *spb.HistoryRecord,
) (int64, error) {
	if t.settings.IsSharedMode() {
		return 0, nil
	}
	if err := t.ensureInit(); err != nil {
		return 0, err
	}

	var step int64
	item := explicitHistoryStepItem(record)
	if item != nil {
		var err error
		step, err = strconv.ParseInt(item.GetValueJson(), 10, 64)
		if err != nil {
			t.logger.CaptureWarn(
				"historystep: ignoring unparseable history _step",
				"value", item.GetValueJson(),
			)
			step = t.nextStep
		}
	}
	if record.GetStep() != nil {
		step = record.GetStep().GetNum()
	}

	step = t.clampStep(step)

	stepValue := strconv.FormatInt(step, 10)
	if item != nil {
		item.ValueJson = stepValue
	} else {
		record.Item = append(record.Item, &spb.HistoryItem{
			NestedKey: []string{"_step"},
			ValueJson: stepValue,
		})
	}

	t.advancePast(step)
	return step, nil
}

func (t *HistoryStepTracker) clampStep(step int64) int64 {
	if step >= t.nextStep {
		return step
	}
	t.logger.CaptureWarn(
		"historystep: _step behind running step, renumbering",
		"provided_step", step,
		"assigned_step", t.nextStep,
	)
	return t.nextStep
}

func (t *HistoryStepTracker) ensureInit() error {
	if t.initialized {
		return nil
	}
	upserter, err := t.runHandle.Upserter()
	if err != nil {
		return fmt.Errorf("historystep: %w", err)
	}
	run := &spb.RunRecord{}
	upserter.FillRunRecord(run)
	t.nextStep = run.GetStartingStep()
	t.initialized = true
	return nil
}

func (t *HistoryStepTracker) advancePast(step int64) {
	if step >= t.nextStep {
		t.nextStep = step + 1
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
