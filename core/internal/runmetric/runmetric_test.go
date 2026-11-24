package runmetric

import (
	"testing"

	"github.com/stretchr/testify/assert"

	"github.com/wandb/wandb/core/internal/pathtree"
	"github.com/wandb/wandb/core/internal/runhistory"
	spb "github.com/wandb/wandb/core/pkg/service_go_proto"
)

func TestStepMetric(t *testing.T) {
	mh := New()
	_ = mh.ProcessRecord(&spb.MetricRecord{Name: "custom_step"})
	_ = mh.ProcessRecord(&spb.MetricRecord{
		GlobName:   "train/*",
		StepMetric: "custom_step",
	})

	if got := mh.StepMetric("train/loss"); got != "custom_step" {
		t.Errorf("expected custom_step, got %q", got)
	}
	if got := mh.StepMetric("other"); got != "" {
		t.Errorf("expected no step metric, got %q", got)
	}
	// An explicit definition without a step metric shadows globs,
	// even an all-matching one.
	_ = mh.ProcessRecord(&spb.MetricRecord{
		GlobName:   "*",
		StepMetric: "custom_step",
	})
	if got := mh.StepMetric("custom_step"); got != "" {
		t.Errorf("expected no step metric, got %q", got)
	}
	// Glob matches are materialized on first lookup: redefining the
	// glob doesn't move already-resolved metrics to a different axis.
	_ = mh.ProcessRecord(&spb.MetricRecord{
		GlobName:   "train/*",
		StepMetric: "other_step",
	})
	if got := mh.StepMetric("train/loss"); got != "custom_step" {
		t.Errorf("expected custom_step, got %q", got)
	}
}

func TestGlobMetricWildcard(t *testing.T) {
	mh := New()

	definedMetric := definedMetric{
		SyncStep:     true,
		Step:         "step_metric",
		IsHidden:     false,
		IsExplicit:   true,
		NoSummary:    false,
		SummaryTypes: 0,
		MetricGoal:   metricGoalUnset,
	}

	mh.globMetrics["*"] = definedMetric

	match, ok := mh.matchGlobMetric("test")
	if !ok || match != definedMetric {
		t.Errorf("Expected match, got %v", match)
	}

	match, ok = mh.matchGlobMetric("test/stuff")
	if !ok || match != definedMetric {
		t.Errorf("Expected match, got %v", match)
	}
}

func TestGlobMetricEndingWildcard(t *testing.T) {
	mh := New()

	definedMetric := definedMetric{
		SyncStep:     true,
		Step:         "step_metric",
		IsHidden:     false,
		IsExplicit:   true,
		NoSummary:    false,
		SummaryTypes: 0,
		MetricGoal:   metricGoalUnset,
	}

	mh.globMetrics["xyz/*"] = definedMetric

	match, ok := mh.matchGlobMetric("test")
	if ok || match == definedMetric {
		t.Errorf("Expected not to match, got %v", match)
	}
	match, ok = mh.matchGlobMetric("xyz/test")
	if !ok || match != definedMetric {
		t.Errorf("Expected match, got %v", match)
	}

}

func TestStepSync(t *testing.T) {
	for _, tc := range []struct {
		name string
		path pathtree.TreePath
	}{
		{"train.step", pathtree.PathOf("train", "step")},
		{".foo", pathtree.PathOf(".foo")},
		{".foo.bar", pathtree.PathOf(".foo", "bar")},
	} {
		t.Run(tc.name, func(t *testing.T) {
			mh := New()
			_ = mh.ProcessRecord(&spb.MetricRecord{Name: tc.name})
			_ = mh.ProcessRecord(&spb.MetricRecord{
				Name:       "loss",
				StepMetric: tc.name,
				Options:    &spb.MetricOptions{StepSync: true},
			})

			first := runhistory.New()
			first.SetFloat(tc.path, 3)
			mh.UpdateMetrics(first)
			second := runhistory.New()
			second.SetFloat(pathtree.PathOf("loss"), 0.5)
			mh.UpdateMetrics(second)
			mh.InsertStepMetrics(second)

			step, ok := second.GetNumber(tc.path)
			assert.True(t, ok)
			assert.Equal(t, 3.0, step)
			records, err := second.ToRecords(true, false)
			assert.NoError(t, err)
			for _, record := range records {
				assert.NotEmpty(t, record.NestedKey[0])
			}
		})
	}
}
