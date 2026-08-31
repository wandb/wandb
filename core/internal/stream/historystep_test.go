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

type trackerConfig struct {
	shared       bool
	startingStep int64
}

type historyStepFixtures struct {
	Tracker *stream.HistoryStepTracker
}

func makeHistoryStepTracker(t *testing.T, cfg trackerConfig) historyStepFixtures {
	t.Helper()
	logger := observabilitytest.NewTestLogger(t)
	settings := wbsettings.From(&spb.Settings{
		RunId:   &wrapperspb.StringValue{Value: "run1"},
		XShared: &wrapperspb.BoolValue{Value: cfg.shared},
	})

	run := &spb.RunRecord{
		Entity:       "test-entity",
		Project:      "test-project",
		RunId:        "test-run",
		StartingStep: cfg.startingStep,
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

	return historyStepFixtures{Tracker: factory.New()}
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
	x := makeHistoryStepTracker(t, trackerConfig{})

	history := &spb.HistoryRecord{
		Item: []*spb.HistoryItem{{
			NestedKey: []string{"loss"},
			ValueJson: "1.23",
		}},
	}

	step, err := x.Tracker.ApplyHistoryStep(history)
	require.NoError(t, err)

	assert.Equal(t, int64(0), step)
	assert.Equal(t, []*spb.HistoryItem{
		{NestedKey: []string{"loss"}, ValueJson: "1.23"},
		{NestedKey: []string{"_step"}, ValueJson: "0"},
	}, history.Item)
}

func TestHistoryStepTracker_PreservesExistingStep(t *testing.T) {
	x := makeHistoryStepTracker(t, trackerConfig{})

	history := &spb.HistoryRecord{
		Item: []*spb.HistoryItem{
			{NestedKey: []string{"loss"}, ValueJson: "1.23"},
			{NestedKey: []string{"_step"}, ValueJson: "7"},
		},
	}

	step, err := x.Tracker.ApplyHistoryStep(history)
	require.NoError(t, err)

	assert.Equal(t, int64(7), step)
	assert.Equal(t, []*spb.HistoryItem{
		{NestedKey: []string{"loss"}, ValueJson: "1.23"},
		{NestedKey: []string{"_step"}, ValueJson: "7"},
	}, history.Item)
}

func TestHistoryStepTracker_RewritesStepBelowStartingStep(t *testing.T) {
	x := makeHistoryStepTracker(t, trackerConfig{startingStep: 2})

	history := &spb.HistoryRecord{
		Item: []*spb.HistoryItem{
			{NestedKey: []string{"loss"}, ValueJson: "0.6"},
			{NestedKey: []string{"_step"}, ValueJson: "0"},
		},
	}

	step, err := x.Tracker.ApplyHistoryStep(history)
	require.NoError(t, err)

	assert.Equal(t, int64(2), step)
	assert.Equal(t, "2", history.Item[1].ValueJson)
}

func TestHistoryStepTracker_OfflineResumedSegmentRewritesSteps(t *testing.T) {
	x := makeHistoryStepTracker(t, trackerConfig{startingStep: 2})

	for _, tc := range []struct {
		localStep string
		loss      string
		wantStep  string
	}{
		{localStep: "0", loss: "0.6", wantStep: "2"},
		{localStep: "1", loss: "0.4", wantStep: "3"},
	} {
		history := &spb.HistoryRecord{
			Item: []*spb.HistoryItem{
				{NestedKey: []string{"loss"}, ValueJson: tc.loss},
				{NestedKey: []string{"_step"}, ValueJson: tc.localStep},
			},
		}
		_, err := x.Tracker.ApplyHistoryStep(history)
		require.NoError(t, err)
		assert.Equal(t, tc.wantStep, historyStepValue(history))
	}
}

func TestHistoryStepTracker_AppliesRecordStep(t *testing.T) {
	x := makeHistoryStepTracker(t, trackerConfig{})

	history := &spb.HistoryRecord{
		Item: []*spb.HistoryItem{{
			NestedKey: []string{"loss"},
			ValueJson: "1.23",
		}},
		Step: &spb.HistoryStep{Num: 5},
	}

	step, err := x.Tracker.ApplyHistoryStep(history)
	require.NoError(t, err)

	assert.Equal(t, int64(5), step)
	assert.Equal(t, []*spb.HistoryItem{
		{NestedKey: []string{"loss"}, ValueJson: "1.23"},
		{NestedKey: []string{"_step"}, ValueJson: "5"},
	}, history.Item)
}

func TestHistoryStepTracker_RewritesRecordStepBelowStartingStep(t *testing.T) {
	x := makeHistoryStepTracker(t, trackerConfig{startingStep: 2})

	history := &spb.HistoryRecord{
		Item: []*spb.HistoryItem{{
			NestedKey: []string{"loss"},
			ValueJson: "1.23",
		}},
		Step: &spb.HistoryStep{Num: 0},
	}

	step, err := x.Tracker.ApplyHistoryStep(history)
	require.NoError(t, err)

	assert.Equal(t, int64(2), step)
	assert.Equal(t, []*spb.HistoryItem{
		{NestedKey: []string{"loss"}, ValueJson: "1.23"},
		{NestedKey: []string{"_step"}, ValueJson: "2"},
	}, history.Item)
}

func TestHistoryStepTracker_RewritesRecordStepBelowRunningStep(t *testing.T) {
	x := makeHistoryStepTracker(t, trackerConfig{})

	first := &spb.HistoryRecord{Step: &spb.HistoryStep{Num: 5}}
	_, err := x.Tracker.ApplyHistoryStep(first)
	require.NoError(t, err)

	history := &spb.HistoryRecord{Step: &spb.HistoryStep{Num: 1}}
	step, err := x.Tracker.ApplyHistoryStep(history)
	require.NoError(t, err)

	assert.Equal(t, int64(6), step)
	assert.Equal(t, []*spb.HistoryItem{
		{NestedKey: []string{"_step"}, ValueJson: "6"},
	}, history.Item)
}

func TestHistoryStepTracker_RewritesUnparseableStep(t *testing.T) {
	x := makeHistoryStepTracker(t, trackerConfig{startingStep: 2})

	history := &spb.HistoryRecord{
		Item: []*spb.HistoryItem{
			{NestedKey: []string{"loss"}, ValueJson: "0.6"},
			{NestedKey: []string{"_step"}, ValueJson: "not-a-number"},
		},
	}

	step, err := x.Tracker.ApplyHistoryStep(history)
	require.NoError(t, err)

	assert.Equal(t, int64(2), step)
	assert.Equal(t, "2", historyStepValue(history))
}

func TestHistoryStepTracker_ErrorsWhenRunNotInitialized(t *testing.T) {
	x := makeHistoryStepTracker(t, trackerConfig{})

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
	_, err = x.Tracker.ApplyHistoryStep(history)
	require.NoError(t, err)
}

func TestHistoryStepTracker_SharedModeLeavesRecordUnchanged(t *testing.T) {
	x := makeHistoryStepTracker(t, trackerConfig{shared: true})

	history := &spb.HistoryRecord{
		Item: []*spb.HistoryItem{{
			NestedKey: []string{"loss"},
			ValueJson: "1.23",
		}},
	}

	step, err := x.Tracker.ApplyHistoryStep(history)
	require.NoError(t, err)

	assert.Equal(t, int64(0), step)
	assert.Equal(t, []*spb.HistoryItem{{
		NestedKey: []string{"loss"},
		ValueJson: "1.23",
	}}, history.Item)
	assert.Empty(t, historyStepValue(history))
}
