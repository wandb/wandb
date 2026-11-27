package stream_test

import (
	"context"
	"testing"

	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"
	"google.golang.org/protobuf/types/known/wrapperspb"

	"github.com/wandb/wandb/core/internal/analytics"
	"github.com/wandb/wandb/core/internal/analyticstest"
	"github.com/wandb/wandb/core/internal/filestreamstats"
	"github.com/wandb/wandb/core/internal/filestreamtest"
	"github.com/wandb/wandb/core/internal/gqlmock"
	"github.com/wandb/wandb/core/internal/runwork"
	"github.com/wandb/wandb/core/internal/stream"
	spb "github.com/wandb/wandb/core/pkg/service_go_proto"
)

func telemetryStats(t *testing.T) (*filestreamstats.Stats, *analyticstest.OpenTelemetryProxyTest) {
	t.Helper()
	proxy := analyticstest.NewOpenTelemetryProxyTest(t)
	recorder := analytics.NewTelemetryRecorder(
		proxy.OpenTelemetryProxy,
		analytics.NewTelemetryContext(),
	)
	stats, err := filestreamstats.New(recorder, filestreamstats.ValueEncodingJSONTyped,
		filestreamstats.WireEncodingJSONL)
	require.NoError(t, err)
	return stats, proxy
}

func partialHistoryRecord(items ...*spb.HistoryItem) *spb.Record {
	return &spb.Record{RecordType: &spb.Record_Request{Request: &spb.Request{
		RequestType: &spb.Request_PartialHistory{PartialHistory: &spb.PartialHistoryRequest{
			Item:   items,
			Step:   &spb.HistoryStep{Num: 1},
			Action: &spb.HistoryAction{Flush: true},
		}},
	}}}
}

func historyReadCounts(
	t *testing.T,
	proxy *analyticstest.OpenTelemetryProxyTest,
	source, segment string,
) int64 {
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

func historyKindCounts(
	t *testing.T,
	proxy *analyticstest.OpenTelemetryProxyTest,
	kind string,
) int64 {
	t.Helper()
	metric, ok := proxy.FindMetricWith(filestreamstats.MetricHistoryKindCount,
		map[string]string{"value_kind": kind})
	if !ok {
		return 0
	}
	return metric.Value
}

var telemetryTestCases = []struct {
	name         string
	items        []*spb.HistoryItem
	kindCounts   map[string]int64
	sourceCounts map[string]int64
}{
	{
		name: "typed",
		items: []*spb.HistoryItem{
			{Key: "typed", Value: &spb.HistoryItem_Text{Text: "2"}},
			{Key: "json", ValueJson: "3"},
		},
		kindCounts:   map[string]int64{"text": 1},
		sourceCounts: map[string]int64{"typed": 1, "json": 1},
	},
}

func TestHandlePartialHistory_EmitHistoryReadCounts(t *testing.T) {
	for _, testCase := range telemetryTestCases {
		t.Run(testCase.name, func(t *testing.T) {
			stats, proxy := telemetryStats(t)
			in := make(chan runwork.Work, stream.BufferSize)
			handler := makeHandlerWithSettings(t, in, "", &spb.Settings{
				XHistoryValueEncoding: wrapperspb.String("json,typed"),
				// skip summary records so we only get a history record
				XServerSideDerivedSummary: wrapperspb.Bool(true),
			}, stats)
			in <- runwork.NoRequest(runwork.WorkRecord{Record: partialHistoryRecord(testCase.items...)})
			got := (<-handler.OutChan()).WorkImpl.(runwork.WorkRecord).Record
			require.NotNil(t, got.GetHistory())
			require.NoError(t, proxy.Shutdown(context.Background()))

			for source, count := range testCase.sourceCounts {
				t.Run(source, func(t *testing.T) {
					assert.Equal(t, count, historyReadCounts(
						t, proxy, source, filestreamstats.SegmentHandlerIngest,
					))
				})
			}
			for kind, count := range testCase.kindCounts {
				kindName := kind
				if kind == "" {
					kindName = "empty"
				}
				t.Run(kindName, func(t *testing.T) {
					assert.Equal(t, count, historyKindCounts(t, proxy, kind))
				})
			}
		})
	}
}

func TestHistoryTelemetry_SenderReadsBeforeUpload(t *testing.T) {
	for _, testCase := range telemetryTestCases {
		t.Run(testCase.name, func(t *testing.T) {
			stats, proxy := telemetryStats(t)
			fileStream := filestreamtest.NewFakeFileStream()
			x := makeSenderWithFileStream(t, gqlmock.NewMockClient(), fileStream, stats)
			sendHistoryItems(x, testCase.items...)
			require.NoError(t, proxy.Shutdown(context.Background()))
			for source, count := range testCase.sourceCounts {
				t.Run(source, func(t *testing.T) {
					assert.Equal(t, count,
						historyReadCounts(t, proxy, source,
							filestreamstats.SegmentUploadIngest,
						),
					)
				})
			}
		})
	}
}
