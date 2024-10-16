package runmetric

import (
	"testing"
)

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
