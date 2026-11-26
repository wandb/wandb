package metricruntime_test

import (
	"testing"
	"time"

	"github.com/stretchr/testify/assert"

	"github.com/wandb/wandb/core/internal/metricruntime"
	"github.com/wandb/wandb/core/internal/pathtree"
	"github.com/wandb/wandb/core/internal/runhistory"
	"github.com/wandb/wandb/core/internal/runsummary"

	spb "github.com/wandb/wandb/core/pkg/service_go_proto"
)

func Test_FromHistoryRecord_RelativeTime(t *testing.T) {
	relativeTimeMs := int64(50000)

	runtime := metricruntime.FromHistoryRecord(
		1234*time.Millisecond,
		runhistory.New(),
		&spb.HistoryRecord{RelativeTimeMs: &relativeTimeMs},
	)

	assert.Equal(t, 51234*time.Millisecond, runtime)
}

func Test_FromHistoryRecord_NoRelativeTime(t *testing.T) {
	history := runhistory.New()
	history.SetFloat(pathtree.PathOf("_runtime"), 7.5)

	runtime := metricruntime.FromHistoryRecord(
		1234*time.Millisecond,
		history,
		&spb.HistoryRecord{},
	)

	assert.Equal(t, 7500*time.Millisecond, runtime)
}

func Test_FromExitRecord_RelativeTime(t *testing.T) {
	relativeTimeMs := int64(50000)

	runtime := metricruntime.FromExitRecord(
		1234*time.Millisecond,
		&spb.RunExitRecord{RelativeTimeMs: &relativeTimeMs},
	)

	assert.Equal(t, 51234*time.Millisecond, runtime)
}

func Test_FromExitRecord_NoRelativeTime(t *testing.T) {
	runtime := metricruntime.FromExitRecord(
		1234*time.Millisecond,
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
