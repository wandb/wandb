package filestreamstats_test

import (
	"context"
	"testing"
	"time"

	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"

	"github.com/wandb/wandb/core/internal/analytics"
	"github.com/wandb/wandb/core/internal/analyticstest"
	"github.com/wandb/wandb/core/internal/filestreamstats"
)

func newStats(t *testing.T) (
	*filestreamstats.Stats,
	*analyticstest.OpenTelemetryProxyTest,
) {
	t.Helper()
	proxy := analyticstest.NewOpenTelemetryProxyTest(t)
	recorder := analytics.NewTelemetryRecorder(
		proxy.OpenTelemetryProxy,
		analytics.NewTelemetryContext(),
	)
	stats, err := filestreamstats.New(
		recorder,
		filestreamstats.ValueEncodingJSON,
		filestreamstats.WireEncodingJSONL,
	)
	require.NoError(t, err)
	return stats, proxy
}

func TestRecordRun_TotalEqualsSumOfSegments(t *testing.T) {
	stats, proxy := newStats(t)

	durations := map[string]time.Duration{
		filestreamstats.SegmentHandlerIngest:   30 * time.Millisecond,
		filestreamstats.SegmentHandlerEmit:     20 * time.Millisecond,
		filestreamstats.SegmentTxLogMarshal:    5 * time.Millisecond,
		filestreamstats.SegmentUploadIngest:    40 * time.Millisecond,
		filestreamstats.SegmentUploadRender:    50 * time.Millisecond,
		filestreamstats.SegmentRequestMarshal:  10 * time.Millisecond,
		filestreamstats.SegmentRequestCompress: 15 * time.Millisecond,
	}

	var want time.Duration
	for segment, duration := range durations {
		stats.RecordSegment(
			t.Context(),
			segment,
			filestreamstats.StreamHistory,
			duration,
		)
		want += duration
	}
	stats.AddRow(4)
	stats.RecordRun(t.Context())
	require.NoError(t, proxy.Shutdown(context.Background()))

	total, ok := proxy.FindMetricWith(
		filestreamstats.MetricEncodeDurationSum,
		map[string]string{},
	)
	require.True(t, ok, "expected a per-run total")
	assert.InDelta(t, want.Microseconds(), total.HistogramSum, 0.0001)

	var summed float64
	for segment := range durations {
		perSegment, ok := proxy.FindMetricWith(
			filestreamstats.MetricEncodeDuration,
			map[string]string{"segment": segment},
		)
		require.True(t, ok, "expected a per-run value for %s", segment)
		summed += perSegment.HistogramSum
	}
	assert.InDelta(t, total.HistogramSum, summed, 0.0001,
		"the total must be the sum of its segments")
}

func TestRecordRequest_ReportsBothBodySizes(t *testing.T) {
	stats, proxy := newStats(t)

	stats.RecordRequest(t.Context(), filestreamstats.RequestReport{
		UncompressedBytes: 8192,
		CompressedBytes:   1024,
		Compressed:        true,
	})
	require.NoError(t, proxy.Shutdown(context.Background()))

	count, ok := proxy.FindMetricWith(
		filestreamstats.MetricRequestCount,
		map[string]string{},
	)
	require.True(t, ok)
	assert.Equal(t, int64(1), count.Value)

	gzipped, ok := proxy.FindMetricWith(
		filestreamstats.MetricRequestSize,
		map[string]string{"content_encoding": filestreamstats.ContentEncodingGzip},
	)
	require.True(t, ok)
	assert.InDelta(t, 1024.0, gzipped.HistogramSum, 1)

	raw, ok := proxy.FindMetricWith(
		filestreamstats.MetricRequestSize,
		map[string]string{"content_encoding": filestreamstats.ContentEncodingRaw},
	)
	require.True(t, ok)
	assert.InDelta(t, 8192.0, raw.HistogramSum, 1)
}

func TestRecordRun_NoDataReportsNothing(t *testing.T) {
	stats, proxy := newStats(t)

	stats.RecordRun(t.Context())
	require.NoError(t, proxy.Shutdown(context.Background()))

	assert.Empty(t, proxy.FindMetrics(filestreamstats.MetricRunCount))
}

func TestRecordRun_SegmentTimeOnlyIsReported(t *testing.T) {
	stats, proxy := newStats(t)

	stats.RecordSegment(
		t.Context(),
		filestreamstats.SegmentHandlerIngest,
		filestreamstats.StreamSummary,
		time.Millisecond,
	)
	stats.RecordRun(t.Context())
	require.NoError(t, proxy.Shutdown(context.Background()))

	metric, ok := proxy.FindMetricWith(
		filestreamstats.MetricEncodeDuration,
		map[string]string{"segment": filestreamstats.SegmentHandlerIngest},
	)
	require.True(t, ok, "a run with only segment time must report it")
	assert.InDelta(t, 1000.0, metric.HistogramSum, 0.0001)
}

func TestNilStats_IsNoop(t *testing.T) {
	var stats *filestreamstats.Stats

	assert.NotPanics(t, func() {
		stats.RecordSegment(
			context.Background(),
			filestreamstats.SegmentUploadRender,
			filestreamstats.StreamHistory,
			time.Millisecond,
		)
		stats.AddRow(1)
		stats.SetTxLogBytes(10)
		stats.RecordRequest(context.Background(), filestreamstats.RequestReport{})
		stats.RecordRun(context.Background())
		stats.SetWireEncoding(filestreamstats.WireEncodingJSONL)
	})
	assert.Empty(t, stats.WireEncoding())
}

func TestSetWireEncoding_AppliesToLaterRecords(t *testing.T) {
	stats, proxy := newStats(t)

	stats.SetWireEncoding(filestreamstats.WireEncodingProtoV1)
	stats.RecordSegment(
		t.Context(),
		filestreamstats.SegmentUploadRender,
		filestreamstats.StreamHistory,
		time.Millisecond,
	)
	stats.AddRow(1)
	stats.RecordRun(t.Context())
	require.NoError(t, proxy.Shutdown(context.Background()))

	metric, ok := proxy.FindMetricWith(
		filestreamstats.MetricEncodeDuration,
		map[string]string{"segment": filestreamstats.SegmentUploadRender},
	)
	require.True(t, ok)
	assert.Equal(t, filestreamstats.WireEncodingProtoV1,
		metric.Attributes["wire_encoding"])
}
