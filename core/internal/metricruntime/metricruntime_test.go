package metricruntime_test

import (
	"testing"
	"time"

	"github.com/stretchr/testify/assert"
	"google.golang.org/protobuf/types/known/wrapperspb"

	"github.com/wandb/wandb/core/internal/gqlmock"
	"github.com/wandb/wandb/core/internal/metricruntime"
	"github.com/wandb/wandb/core/internal/pathtree"
	"github.com/wandb/wandb/core/internal/runhistory"
	"github.com/wandb/wandb/core/internal/runsummary"
	"github.com/wandb/wandb/core/internal/runupserter"
	"github.com/wandb/wandb/core/internal/runupsertertest"
	"github.com/wandb/wandb/core/internal/settings"

	spb "github.com/wandb/wandb/core/pkg/service_go_proto"
)

// upserterWithStartRuntime returns an upserter whose StartRuntime
// returns the given value by simulating a resumed run.
func upserterWithStartRuntime(
	t *testing.T,
	runtime time.Duration,
) *runupserter.RunUpserter {
	t.Helper()

	mockClient := gqlmock.NewMockClient()
	runupsertertest.StubRunResumeStatusWithStepAndRuntime(t,
		mockClient,
		/*step*/ 10,
		runtime.Seconds(),
	)
	runupsertertest.StubUpsertBucket(t, mockClient)

	return runupsertertest.NewTestUpserter(t,
		"test-entity",
		"test-project",
		"test-id",
		runupserter.RunUpserterParams{
			GraphqlClientOrNil: mockClient,
			Settings: settings.From(&spb.Settings{
				Resume: wrapperspb.String("must"),
			}),
		},
	)
}

func Test_FromHistoryRecord_RelativeTime(t *testing.T) {
	upserter := upserterWithStartRuntime(t, 1234*time.Millisecond)
	relativeTimeMs := int64(50000)

	runtime := metricruntime.FromHistoryRecord(
		upserter,
		runhistory.New(),
		&spb.HistoryRecord{RelativeTimeMs: &relativeTimeMs},
	)

	assert.Equal(t, 51234*time.Millisecond, runtime)
}

func Test_FromHistoryRecord_NoRelativeTime(t *testing.T) {
	upserter := upserterWithStartRuntime(t, 1234*time.Millisecond)
	history := runhistory.New()
	history.SetFloat(pathtree.PathOf("_runtime"), 7.5)

	runtime := metricruntime.FromHistoryRecord(
		upserter,
		history,
		&spb.HistoryRecord{},
	)

	assert.Equal(t, 7500*time.Millisecond, runtime)
}

func Test_FromExitRecord_RelativeTime(t *testing.T) {
	upserter := upserterWithStartRuntime(t, 1234*time.Millisecond)
	relativeTimeMs := int64(50000)

	runtime := metricruntime.FromExitRecord(
		upserter,
		&spb.RunExitRecord{RelativeTimeMs: &relativeTimeMs},
	)

	assert.Equal(t, 51234*time.Millisecond, runtime)
}

func Test_FromExitRecord_NoRelativeTime(t *testing.T) {
	upserter := upserterWithStartRuntime(t, 1234*time.Millisecond)

	runtime := metricruntime.FromExitRecord(
		upserter,
		&spb.RunExitRecord{Runtime: 14},
	)

	assert.Equal(t, 14*time.Second, runtime)
}

func Test_SetInHistory(t *testing.T) {
	history := runhistory.New()

	metricruntime.SetInHistory(history, 1234*time.Millisecond)

	value, _ := history.GetNumber(pathtree.PathOf("_runtime"))
	assert.EqualValues(t, 1.234, value)
}

func Test_SetInSummary(t *testing.T) {
	summary := runsummary.New()

	metricruntime.SetInSummary(
		runsummary.NoUpdates(),
		4321*time.Millisecond,
	).Apply(summary)

	assert.Equal(t, map[string]any{
		"_runtime": float64(4.321),
		"_wandb": map[string]any{
			"runtime": float64(4.321),
		},
	}, summary.ToNestedMaps())
}

func Test_IgnoreInSummary(t *testing.T) {
	summary := runsummary.New()
	updates := metricruntime.SetInSummary(
		runsummary.NoUpdates(),
		4321*time.Millisecond,
	)

	metricruntime.IgnoreInSummary(updates)
	updates.Apply(summary)

	assert.Empty(t, summary.ToNestedMaps())
}
