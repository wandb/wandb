package filestreamstats_test

import (
	"context"
	"math"
	"testing"

	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"

	"github.com/wandb/wandb/core/internal/analyticstest"
	"github.com/wandb/wandb/core/internal/filestreamstats"
	spb "github.com/wandb/wandb/core/pkg/service_go_proto"
)

func historyReadCounts(t *testing.T, proxy *analyticstest.OpenTelemetryProxyTest, source string, segment string) int64 {
	t.Helper()
	metric, ok := proxy.FindMetricWith(filestreamstats.MetricHistoryReadCount,
		map[string]string{
			"value_read_source": source,
			"segment":           segment})
	if !ok {
		return 0
	}
	return metric.Value
}

func historyKindCounts(t *testing.T, proxy *analyticstest.OpenTelemetryProxyTest, kind string) int64 {
	t.Helper()
	metric, ok := proxy.FindMetricWith(filestreamstats.MetricHistoryKindCount,
		map[string]string{"value_kind": kind})
	if !ok {
		return 0
	}
	return metric.Value
}

func TestHistoryCounters_RecordHistoryReads(t *testing.T) {
	segment := filestreamstats.SegmentHandlerIngest

	stats, proxy := newStats(t)
	reads := filestreamstats.HistoryReadCounts{}
	reads.Add(&spb.HistoryItem{Key: "read-key", ValueJson: "1"})
	reads.Add(&spb.HistoryItem{Key: "read-key", Value: &spb.HistoryItem_Integer{Integer: 7}})
	stats.RecordHistoryReads(t.Context(), segment, reads)
	require.NoError(t, proxy.Shutdown(context.Background()))
	sources := []string{
		filestreamstats.ValueReadSourceJSON,
		filestreamstats.ValueReadSourceTyped,
	}
	for _, source := range sources {
		assert.Equal(t, int64(1), historyReadCounts(t, proxy, source, segment))
	}
}

func metricValue(t *testing.T, proxy *analyticstest.OpenTelemetryProxyTest, name string) int64 {
	t.Helper()
	metric, ok := proxy.FindMetric(name)
	require.True(t, ok, "missing metric %s", name)
	return metric.Value
}

func TestHistoryCounters_RecordHistoryEmitted(t *testing.T) {
	stats, proxy := newStats(t)
	jsonValue2 := `{"é":"test-json-value"}`
	stats.RecordHistoryEmitted(t.Context(), []*spb.HistoryItem{
		{Key: "test-null", Value: &spb.HistoryItem_None{}},
		{Key: "test-bool", Value: &spb.HistoryItem_Boolean{Boolean: false}},
		{Key: "test-int", Value: &spb.HistoryItem_Integer{Integer: 0}},
		{Key: "test-number", Value: &spb.HistoryItem_Number{Number: math.NaN()}},
		{Key: "test-number", Value: &spb.HistoryItem_Number{Number: math.Inf(1)}},
		{Key: "test-number", Value: &spb.HistoryItem_Number{Number: math.Inf(-1)}},
		{Key: "test-number", Value: &spb.HistoryItem_Number{Number: math.Copysign(0, -1)}},
		{Key: "test-text", Value: &spb.HistoryItem_Text{Text: "test-text-value"}},
		{Key: "test-json", Value: &spb.HistoryItem_Json{Json: jsonValue2}},
		{Key: "test-legacy", ValueJson: `{"x":1}`},
	})
	require.NoError(t, proxy.Shutdown(context.Background()))

	assert.Equal(t, int64(1), historyKindCounts(t, proxy, "none"))
	assert.Equal(t, int64(1), historyKindCounts(t, proxy, "boolean"))
	assert.Equal(t, int64(1), historyKindCounts(t, proxy, "integer"))
	assert.Equal(t, int64(4), historyKindCounts(t, proxy, "number"))
	assert.Equal(t, int64(1), historyKindCounts(t, proxy, "text"))
	assert.Equal(t, int64(1), historyKindCounts(t, proxy, "json"))

	assert.Equal(t, int64(3), metricValue(t, proxy, filestreamstats.MetricHistoryNonfiniteCount))
	assert.Equal(t, int64(1), metricValue(t, proxy, filestreamstats.MetricHistoryTypedJSONCount))
	assert.Equal(t, int64(len(jsonValue2)), metricValue(t, proxy, filestreamstats.MetricHistoryTypedJSONBytes))
}

func TestHistoryCounters_JSONOnlyEmissionHasNoTypedKinds(t *testing.T) {
	stats, proxy := newStats(t)
	stats.RecordHistoryEmitted(t.Context(), []*spb.HistoryItem{
		{Key: "test-key", ValueJson: `{"value":1}`},
	})
	require.NoError(t, proxy.Shutdown(context.Background()))
	assert.Empty(t, proxy.FindMetrics(filestreamstats.MetricHistoryKindCount))
	assert.Empty(t, proxy.FindMetrics(filestreamstats.MetricHistoryTypedJSONCount))
}
