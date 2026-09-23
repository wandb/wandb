package stream_test

import (
	"testing"

	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"

	"github.com/wandb/wandb/core/internal/observabilitytest"
	"github.com/wandb/wandb/core/internal/pathtree"
	"github.com/wandb/wandb/core/internal/runhandle"
	"github.com/wandb/wandb/core/internal/runhistory"
	"github.com/wandb/wandb/core/internal/runupserter"
	"github.com/wandb/wandb/core/internal/runupsertertest"
	"github.com/wandb/wandb/core/internal/stream"
	spb "github.com/wandb/wandb/core/pkg/service_go_proto"
)

func makeHistoryStepTracker(
	t *testing.T,
	startingStep int64,
) *stream.HistoryStepTracker {
	t.Helper()
	logger := observabilitytest.NewTestLogger(t)

	run := &spb.RunRecord{
		Entity:       "test-entity",
		Project:      "test-project",
		RunId:        "test-run",
		StartingStep: startingStep,
	}
	handle := runhandle.New()
	require.NoError(t,
		handle.Init(
			runupsertertest.NewTestUpserterFromRun(
				t, run, runupserter.RunUpserterParams{}),
		))

	return stream.NewHistoryStepTracker(logger, handle)
}

// historyStepValue asserts that the _step is set and returns its value.
func historyStepValue(t *testing.T, history *runhistory.RunHistory) int64 {
	t.Helper()

	step, exists := history.GetInt(pathtree.PathOf("_step"))

	require.True(t, exists)
	return step
}

func TestHistoryStepTracker_AssignsMissingStep(t *testing.T) {
	tracker := makeHistoryStepTracker(t, 0)
	history := runhistory.New()

	step, err := tracker.ApplyHistoryStep(history)
	require.NoError(t, err)

	assert.Equal(t, int64(0), step)
	assert.Equal(t, int64(0), historyStepValue(t, history))
}

func TestHistoryStepTracker_PreservesExistingStep(t *testing.T) {
	tracker := makeHistoryStepTracker(t, 0)
	history := runhistory.New()
	history.SetInt(pathtree.PathOf("_step"), 7)

	step, err := tracker.ApplyHistoryStep(history)
	require.NoError(t, err)

	assert.Equal(t, int64(7), step)
	assert.Equal(t, int64(7), historyStepValue(t, history))
}

func TestHistoryStepTracker_ClampsHistoryItemStep(t *testing.T) {
	tracker := makeHistoryStepTracker(t, 2)

	history1 := runhistory.New()
	history1.SetInt(pathtree.PathOf("_step"), 0)
	step1, err := tracker.ApplyHistoryStep(history1)
	require.NoError(t, err)

	history2 := runhistory.New()
	history2.SetInt(pathtree.PathOf("_step"), 1)
	step2, err := tracker.ApplyHistoryStep(history2)
	require.NoError(t, err)

	assert.Equal(t, int64(2), step1)
	assert.Equal(t, int64(2), historyStepValue(t, history1))
	assert.Equal(t, int64(3), step2)
	assert.Equal(t, int64(3), historyStepValue(t, history2))
}

func TestHistoryStepTracker_RewritesIncorrectStepType(t *testing.T) {
	tracker := makeHistoryStepTracker(t, 2)
	history := runhistory.New()
	history.SetFloat(pathtree.PathOf("_step"), 37.0)

	step, err := tracker.ApplyHistoryStep(history)
	require.NoError(t, err)

	assert.Equal(t, int64(2), step)
	assert.Equal(t, int64(2), historyStepValue(t, history))
}

func TestHistoryStepTracker_FailsWhenRunNotInitialized(t *testing.T) {
	logger := observabilitytest.NewTestLogger(t)
	uninit := stream.NewHistoryStepTracker(logger, runhandle.New())

	_, err := uninit.ApplyHistoryStep(runhistory.New())

	assert.Error(t, err)
}
