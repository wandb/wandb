package stream

import (
	"fmt"

	"github.com/wandb/wandb/core/internal/observability"
	"github.com/wandb/wandb/core/internal/pathtree"
	"github.com/wandb/wandb/core/internal/runhandle"
	"github.com/wandb/wandb/core/internal/runhistory"
)

var stepKey = pathtree.PathOf("_step")

// HistoryStepTracker assigns increasing _step values to history rows.
type HistoryStepTracker struct {
	logger    *observability.CoreLogger
	runHandle *runhandle.RunHandle

	// nextStep is the minimum step for the next history row.
	nextStep    int64
	initialized bool
}

func NewHistoryStepTracker(
	logger *observability.CoreLogger,
	runHandle *runhandle.RunHandle,
) *HistoryStepTracker {
	return &HistoryStepTracker{
		logger:    logger,
		runHandle: runHandle,
	}
}

// ApplyHistoryStep ensures there is a valid "_step" metric, at least one
// larger than for the previous row.
//
// err is non-nil when the run is not initialized; the caller must skip
// the history row.
func (t *HistoryStepTracker) ApplyHistoryStep(
	history *runhistory.RunHistory,
) (int64, error) {
	if err := t.ensureInit(); err != nil {
		return 0, err
	}

	step, exists := history.GetInt(stepKey)

	if exists {
		step = t.clampStep(step)
	} else {
		step = t.nextStep
	}

	history.SetInt(stepKey, step)
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
	t.nextStep = upserter.StartingStep()
	t.initialized = true
	return nil
}

func (t *HistoryStepTracker) advancePast(step int64) {
	if step >= t.nextStep {
		t.nextStep = step + 1
	}
}
