package stream

import (
	"github.com/wandb/wandb/core/internal/observability"
	"github.com/wandb/wandb/core/internal/pathtree"
	"github.com/wandb/wandb/core/internal/runhistory"
	"github.com/wandb/wandb/core/internal/runupserter"
)

var stepKey = pathtree.PathOf("_step")

// HistoryStepTracker assigns increasing _step values to history rows.
type HistoryStepTracker struct {
	logger *observability.CoreLogger

	// nextStep is the minimum step for the next history row.
	nextStep    int64
	initialized bool
}

func NewHistoryStepTracker(
	logger *observability.CoreLogger,
) *HistoryStepTracker {
	return &HistoryStepTracker{
		logger: logger,
	}
}

// ApplyHistoryStep ensures there is a valid "_step" metric, at least one
// larger than for the previous row.
func (t *HistoryStepTracker) ApplyHistoryStep(
	upserter *runupserter.RunUpserter,
	history *runhistory.RunHistory,
) int64 {
	t.maybeInit(upserter)

	step, exists := history.GetInt(stepKey)

	if exists {
		step = t.clampStep(step)
	} else {
		step = t.nextStep
	}

	history.SetInt(stepKey, step)
	t.advancePast(step)
	return step
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

func (t *HistoryStepTracker) maybeInit(upserter *runupserter.RunUpserter) {
	if t.initialized {
		return
	}

	t.nextStep = upserter.StartingStep()
	t.initialized = true
}

func (t *HistoryStepTracker) advancePast(step int64) {
	if step >= t.nextStep {
		t.nextStep = step + 1
	}
}
