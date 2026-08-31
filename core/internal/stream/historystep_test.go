package stream_test

import (
	"testing"

	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"
	"google.golang.org/protobuf/types/known/wrapperspb"

	"github.com/wandb/wandb/core/internal/observabilitytest"
	"github.com/wandb/wandb/core/internal/runhandle"
	"github.com/wandb/wandb/core/internal/runupserter"
	"github.com/wandb/wandb/core/internal/runupsertertest"
	wbsettings "github.com/wandb/wandb/core/internal/settings"
	"github.com/wandb/wandb/core/internal/stream"
	spb "github.com/wandb/wandb/core/pkg/service_go_proto"
)

func makeHistoryStepTracker(t *testing.T, startingStep int64) *stream.HistoryStepTracker {
	t.Helper()
	logger := observabilitytest.NewTestLogger(t)
	settings := wbsettings.From(&spb.Settings{
		RunId: &wrapperspb.StringValue{Value: "run1"},
	})

	run := &spb.RunRecord{
		Entity:       "test-entity",
		Project:      "test-project",
		RunId:        "test-run",
		StartingStep: startingStep,
	}
	handle := runhandle.New()
	require.NoError(t, handle.Init(
		runupsertertest.NewTestUpserterFromRun(t, run, runupserter.RunUpserterParams{}),
	))
	factory := &stream.HistoryStepTrackerFactory{
		Logger:    logger,
		Settings:  settings,
		RunHandle: handle,
	}

	return factory.New()
}

func historyStepValue(record *spb.HistoryRecord) string {
	for _, item := range record.Item {
		if item.GetKey() == "_step" ||
			(len(item.GetNestedKey()) == 1 && item.GetNestedKey()[0] == "_step") {
			return item.ValueJson
		}
	}
	return ""
}

func TestHistoryStepTracker_AssignsMissingStep(t *testing.T) {
	tracker := makeHistoryStepTracker(t, 0)

	history := &spb.HistoryRecord{
		Item: []*spb.HistoryItem{{
			NestedKey: []string{"loss"},
			ValueJson: "1.23",
		}},
	}

	step, err := tracker.ApplyHistoryStep(history)
	require.NoError(t, err)

	assert.Equal(t, int64(0), step)
	assert.Equal(t, []*spb.HistoryItem{
		{NestedKey: []string{"loss"}, ValueJson: "1.23"},
		{NestedKey: []string{"_step"}, ValueJson: "0"},
	}, history.Item)
}

func TestHistoryStepTracker_PreservesExistingStep(t *testing.T) {
	tracker := makeHistoryStepTracker(t, 0)

	history := &spb.HistoryRecord{
		Item: []*spb.HistoryItem{
			{NestedKey: []string{"loss"}, ValueJson: "1.23"},
			{NestedKey: []string{"_step"}, ValueJson: "7"},
		},
	}

	step, err := tracker.ApplyHistoryStep(history)
	require.NoError(t, err)

	assert.Equal(t, int64(7), step)
	assert.Equal(t, []*spb.HistoryItem{
		{NestedKey: []string{"loss"}, ValueJson: "1.23"},
		{NestedKey: []string{"_step"}, ValueJson: "7"},
	}, history.Item)
}

func TestHistoryStepTracker_ClampsHistoryItemStep(t *testing.T) {
	tracker := makeHistoryStepTracker(t, 2)

	history1 := &spb.HistoryRecord{
		Item: []*spb.HistoryItem{
			{NestedKey: []string{"loss"}, ValueJson: "0.6"},
			{NestedKey: []string{"_step"}, ValueJson: "0"},
		},
	}
	step1, err := tracker.ApplyHistoryStep(history1)
	require.NoError(t, err)
	assert.Equal(t, int64(2), step1)
	assert.Equal(t, "2", historyStepValue(history1))

	history2 := &spb.HistoryRecord{
		Item: []*spb.HistoryItem{
			{NestedKey: []string{"loss"}, ValueJson: "0.4"},
			{NestedKey: []string{"_step"}, ValueJson: "1"},
		},
	}
	step2, err := tracker.ApplyHistoryStep(history2)
	require.NoError(t, err)
	assert.Equal(t, int64(3), step2)
	assert.Equal(t, "3", historyStepValue(history2))
}

func TestHistoryStepTracker_AppliesRecordStep(t *testing.T) {
	tracker := makeHistoryStepTracker(t, 0)

	history := &spb.HistoryRecord{
		Item: []*spb.HistoryItem{{
			NestedKey: []string{"loss"},
			ValueJson: "1.23",
		}},
		Step: &spb.HistoryStep{Num: 5},
	}

	step, err := tracker.ApplyHistoryStep(history)
	require.NoError(t, err)

	assert.Equal(t, int64(5), step)
	assert.Equal(t, []*spb.HistoryItem{
		{NestedKey: []string{"loss"}, ValueJson: "1.23"},
		{NestedKey: []string{"_step"}, ValueJson: "5"},
	}, history.Item)
}

func TestHistoryStepTracker_ClampsRecordStep(t *testing.T) {
	tracker := makeHistoryStepTracker(t, 5)

	history1 := &spb.HistoryRecord{}
	step1, err := tracker.ApplyHistoryStep(history1)
	require.NoError(t, err)
	assert.Equal(t, int64(5), step1)
	assert.Equal(t, "5", historyStepValue(history1))

	history2 := &spb.HistoryRecord{Step: &spb.HistoryStep{Num: 1}}
	step2, err := tracker.ApplyHistoryStep(history2)
	require.NoError(t, err)

	assert.Equal(t, int64(6), step2)
	assert.Equal(t, "6", historyStepValue(history2))
}

func TestHistoryStepTracker_RewritesUnparseableStep(t *testing.T) {
	tracker := makeHistoryStepTracker(t, 2)

	history := &spb.HistoryRecord{
		Item: []*spb.HistoryItem{
			{NestedKey: []string{"loss"}, ValueJson: "0.6"},
			{NestedKey: []string{"_step"}, ValueJson: "not-a-number"},
		},
	}

	step, err := tracker.ApplyHistoryStep(history)
	require.NoError(t, err)

	assert.Equal(t, int64(2), step)
	assert.Equal(t, "2", historyStepValue(history))
}

func TestHistoryStepTracker_ErrorsWhenRunNotInitialized(t *testing.T) {
	tracker := makeHistoryStepTracker(t, 0)

	logger := observabilitytest.NewTestLogger(t)
	settings := wbsettings.From(&spb.Settings{
		RunId: &wrapperspb.StringValue{Value: "run1"},
	})
	uninit := (&stream.HistoryStepTrackerFactory{
		Logger:    logger,
		Settings:  settings,
		RunHandle: runhandle.New(),
	}).New()

	history := &spb.HistoryRecord{
		Item: []*spb.HistoryItem{{
			NestedKey: []string{"loss"},
			ValueJson: "1.23",
		}},
	}

	_, err := uninit.ApplyHistoryStep(history)
	require.Error(t, err)

	// A tracker with an initialized handle still works.
	_, err = tracker.ApplyHistoryStep(history)
	require.NoError(t, err)
}
