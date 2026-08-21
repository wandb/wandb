package stream_test

import (
	"testing"

	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"
	"google.golang.org/protobuf/types/known/wrapperspb"

	"github.com/wandb/wandb/core/internal/observabilitytest"
	"github.com/wandb/wandb/core/internal/runsummary"
	wbsettings "github.com/wandb/wandb/core/internal/settings"
	"github.com/wandb/wandb/core/internal/stream"
	spb "github.com/wandb/wandb/core/pkg/service_go_proto"
)

type historyStepFixtures struct {
	Tracker    *stream.HistoryStepTracker
	RunSummary *runsummary.RunSummary
}

func makeHistoryStepTracker(
	t *testing.T,
	shared bool,
	serverSideDerivedSummary bool,
) historyStepFixtures {
	t.Helper()
	logger := observabilitytest.NewTestLogger(t)
	settings := wbsettings.From(&spb.Settings{
		RunId:   &wrapperspb.StringValue{Value: "run1"},
		XShared: &wrapperspb.BoolValue{Value: shared},
		XServerSideDerivedSummary: &wrapperspb.BoolValue{
			Value: serverSideDerivedSummary,
		},
	})
	runSummary := runsummary.New()
	return historyStepFixtures{
		Tracker: (&stream.HistoryStepTrackerFactory{
			Logger:     logger,
			Settings:   settings,
			RunSummary: runSummary,
		}).New(),
		RunSummary: runSummary,
	}
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

func summaryStepValue(t *testing.T, rs *runsummary.RunSummary) string {
	t.Helper()
	summary, err := rs.ToRecords()
	require.NoError(t, err)
	for _, item := range summary {
		if item.GetKey() == "_step" {
			return item.GetValueJson()
		}
	}
	return ""
}

func TestHistoryStepTracker_AssignsMissingStep(t *testing.T) {
	x := makeHistoryStepTracker(t, false /*shared*/, false /*serverSideDerivedSummary*/)

	history := &spb.HistoryRecord{
		Item: []*spb.HistoryItem{{
			NestedKey: []string{"loss"},
			ValueJson: "1.23",
		}},
	}

	x.Tracker.ApplyHistoryStep(history)

	assert.Equal(t, []*spb.HistoryItem{
		{NestedKey: []string{"loss"}, ValueJson: "1.23"},
		{NestedKey: []string{"_step"}, ValueJson: "0"},
	}, history.Item)
	assert.Equal(t, int64(0), history.GetStep().GetNum())
}

func TestHistoryStepTracker_PreservesExistingStep(t *testing.T) {
	x := makeHistoryStepTracker(t, false /*shared*/, false /*serverSideDerivedSummary*/)

	history := &spb.HistoryRecord{
		Item: []*spb.HistoryItem{
			{NestedKey: []string{"loss"}, ValueJson: "1.23"},
			{NestedKey: []string{"_step"}, ValueJson: "7"},
		},
	}

	x.Tracker.ApplyHistoryStep(history)

	assert.Equal(t, []*spb.HistoryItem{
		{NestedKey: []string{"loss"}, ValueJson: "1.23"},
		{NestedKey: []string{"_step"}, ValueJson: "7"},
	}, history.Item)
}

func TestHistoryStepTracker_RewritesStepBelowStartingStep(t *testing.T) {
	x := makeHistoryStepTracker(t, false /*shared*/, false /*serverSideDerivedSummary*/)
	x.Tracker.SeedStartingStep(2)

	history := &spb.HistoryRecord{
		Item: []*spb.HistoryItem{
			{NestedKey: []string{"loss"}, ValueJson: "0.6"},
			{NestedKey: []string{"_step"}, ValueJson: "0"},
		},
	}

	x.Tracker.ApplyHistoryStep(history)

	assert.Equal(t, "2", history.Item[1].ValueJson)
}

func TestHistoryStepTracker_OfflineResumedSegmentRewritesSteps(t *testing.T) {
	x := makeHistoryStepTracker(t, false /*shared*/, false /*serverSideDerivedSummary*/)
	x.Tracker.SeedStartingStep(2)

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
		x.Tracker.ApplyHistoryStep(history)
		assert.Equal(t, tc.wantStep, historyStepValue(history))
	}
}

func TestHistoryStepTracker_AppliesRecordStep(t *testing.T) {
	x := makeHistoryStepTracker(t, false /*shared*/, false /*serverSideDerivedSummary*/)

	history := &spb.HistoryRecord{
		Item: []*spb.HistoryItem{{
			NestedKey: []string{"loss"},
			ValueJson: "1.23",
		}},
		Step: &spb.HistoryStep{Num: 5},
	}

	x.Tracker.ApplyHistoryStep(history)

	assert.Equal(t, []*spb.HistoryItem{
		{NestedKey: []string{"loss"}, ValueJson: "1.23"},
		{NestedKey: []string{"_step"}, ValueJson: "5"},
	}, history.Item)
}

func TestHistoryStepTracker_NextStep(t *testing.T) {
	x := makeHistoryStepTracker(t, false /*shared*/, false /*serverSideDerivedSummary*/)
	x.Tracker.SeedStartingStep(2)

	assert.Equal(t, int64(2), x.Tracker.NextStep())

	_, ok := x.Tracker.ApplyHistoryStep(&spb.HistoryRecord{
		Item: []*spb.HistoryItem{{
			NestedKey: []string{"loss"},
			ValueJson: "1.0",
		}},
	})
	require.True(t, ok)

	assert.Equal(t, int64(3), x.Tracker.NextStep())
}

func TestHistoryStepTracker_DropsUserProvidedStepBelowStartingStep(t *testing.T) {
	x := makeHistoryStepTracker(t, false /*shared*/, false /*serverSideDerivedSummary*/)
	x.Tracker.SeedStartingStep(2)

	history := &spb.HistoryRecord{
		Item: []*spb.HistoryItem{{
			NestedKey: []string{"loss"},
			ValueJson: "1.23",
		}},
		Step: &spb.HistoryStep{Num: 0},
	}

	_, ok := x.Tracker.ApplyHistoryStep(history)

	assert.False(t, ok)
	assert.Equal(t, []*spb.HistoryItem{{
		NestedKey: []string{"loss"},
		ValueJson: "1.23",
	}}, history.Item)
	assert.Equal(t, int64(0), history.GetStep().GetNum())
}

func TestHistoryStepTracker_DropsUserProvidedStepBelowRunningStep(t *testing.T) {
	x := makeHistoryStepTracker(t, false /*shared*/, false /*serverSideDerivedSummary*/)

	first := &spb.HistoryRecord{Step: &spb.HistoryStep{Num: 5}}
	_, ok := x.Tracker.ApplyHistoryStep(first)
	require.True(t, ok)

	history := &spb.HistoryRecord{Step: &spb.HistoryStep{Num: 1}}
	_, ok = x.Tracker.ApplyHistoryStep(history)

	assert.False(t, ok)
	assert.Equal(t, int64(1), history.GetStep().GetNum())
	assert.Empty(t, history.Item)
}

func TestHistoryStepTracker_DerivesSummaryStep(t *testing.T) {
	x := makeHistoryStepTracker(t, false /*shared*/, false /*serverSideDerivedSummary*/)

	history := &spb.HistoryRecord{
		Item: []*spb.HistoryItem{{
			NestedKey: []string{"loss"},
			ValueJson: "1.23",
		}},
	}

	x.Tracker.ApplyHistoryStep(history)

	assert.Equal(t, "0", summaryStepValue(t, x.RunSummary))
}

func TestHistoryStepTracker_SharedModeSkipsSummaryStep(t *testing.T) {
	x := makeHistoryStepTracker(t, true /*shared*/, false /*serverSideDerivedSummary*/)

	history := &spb.HistoryRecord{
		Item: []*spb.HistoryItem{{
			NestedKey: []string{"loss"},
			ValueJson: "1.23",
		}},
	}

	x.Tracker.ApplyHistoryStep(history)

	summary, err := x.RunSummary.ToRecords()
	require.NoError(t, err)
	for _, item := range summary {
		assert.NotEqual(t, "_step", item.GetKey())
	}
}

func TestHistoryStepTracker_PreservesForwardedAggregation(t *testing.T) {
	x := makeHistoryStepTracker(t, false /*shared*/, false /*serverSideDerivedSummary*/)

	// Simulate the handler forwarding a define_metric("acc", summary="max")
	// aggregation of 0.9.
	require.NoError(t, runsummary.FromProto(&spb.SummaryRecord{
		Update: []*spb.SummaryItem{{
			Key:       "acc",
			ValueJson: "0.9",
		}},
	}).Apply(x.RunSummary))

	// A later history row logs a lower value; ApplyHistoryStep must only
	// touch _step and must not clobber the forwarded max.
	x.Tracker.ApplyHistoryStep(&spb.HistoryRecord{
		Item: []*spb.HistoryItem{{
			NestedKey: []string{"acc"},
			ValueJson: "0.4",
		}},
	})

	summary, err := x.RunSummary.ToRecords()
	require.NoError(t, err)

	var accValue, stepValue string
	for _, item := range summary {
		switch item.GetKey() {
		case "acc":
			accValue = item.GetValueJson()
		case "_step":
			stepValue = item.GetValueJson()
		}
	}
	assert.Equal(t, "0.9", accValue)
	assert.Equal(t, "0", stepValue)
}

func TestHistoryStepTracker_RebasedStepUpdatesSummaryStep(t *testing.T) {
	x := makeHistoryStepTracker(t, false /*shared*/, false /*serverSideDerivedSummary*/)
	x.Tracker.SeedStartingStep(2)

	// An offline-resumed row logged with a local step of 0 is rebased forward
	// to the run's starting step; the summary _step must track the rebased
	// value, not the stale local one.
	x.Tracker.ApplyHistoryStep(&spb.HistoryRecord{
		Item: []*spb.HistoryItem{
			{NestedKey: []string{"loss"}, ValueJson: "0.6"},
			{NestedKey: []string{"_step"}, ValueJson: "0"},
		},
	})

	assert.Equal(t, "2", summaryStepValue(t, x.RunSummary))
}
