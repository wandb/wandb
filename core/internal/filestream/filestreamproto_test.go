package filestream

import (
	"context"
	"net/url"
	"testing"
	"time"

	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"
	"google.golang.org/protobuf/proto"
	"google.golang.org/protobuf/types/known/timestamppb"

	"github.com/wandb/wandb/core/internal/apitest"
	"github.com/wandb/wandb/core/internal/featurechecker"
	filestreamv1 "github.com/wandb/wandb/core/internal/filestream/proto"
	"github.com/wandb/wandb/core/internal/observability"
	"github.com/wandb/wandb/core/internal/runsummary"
	"github.com/wandb/wandb/core/internal/settings"
	"github.com/wandb/wandb/core/internal/sparselist"
	spb "github.com/wandb/wandb/core/pkg/service_go_proto"
)

func newProtoTestStream(
	t *testing.T,
	features map[spb.ServerFeature]bool,
) (*fileStream, *apitest.FakeClient) {
	t.Helper()
	baseURL, err := url.Parse("https://api.wandb.test")
	require.NoError(t, err)
	client := apitest.NewFakeClient(baseURL.String())
	client.SetResponse(&apitest.TestResponse{StatusCode: 200}, nil)
	factory := FileStreamFactory{
		BaseURL:         baseURL,
		FeatureProvider: featurechecker.NewPreloaded(features),
		Logger:          observability.NewNoOpLogger(),
		Printer:         observability.NewPrinter(0),
		Settings:        settings.New(),
	}
	return factory.New(client, context.Background(), time.Hour, nil).(*fileStream), client
}

func TestProtobufBody(t *testing.T) {
	fs, client := newProtoTestStream(t, map[spb.ServerFeature]bool{
		spb.ServerFeature_TYPED_SYSTEM_METRICS: true,
	})
	writer := &spb.WriterInfo{Id: "writer", Hostname: "host", Rank: proto.Int32(0)}
	samples := []*spb.SystemMetricsRecord{
		{
			Writer:             writer,
			Sequence:           7,
			Timestamp:          timestamppb.New(time.Unix(100, 123)),
			IntervalMs:         2000,
			SamplingIntervalMs: 1000,
		},
		{
			Writer:             proto.CloneOf(writer),
			Sequence:           9,
			Timestamp:          timestamppb.New(time.Unix(102, 456)),
			IntervalMs:         3000,
			SamplingIntervalMs: 1000,
		},
	}
	console := &sparselist.SparseList[string]{}
	console.Put(2, "console 1")
	console.Put(3, "console 2")
	request := &FileStreamRequest{
		HistoryLines: []string{`{"loss":1}`, `{"loss":2}`},
		ConsoleLines: console,
		SummaryUpdates: runsummary.FromProto(&spb.SummaryRecord{
			Update: []*spb.SummaryItem{{Key: "loss", ValueJson: "2"}},
		}),
		UploadedFiles: map[string]struct{}{"model.bin": {}},
		Preempting:    true,
		Complete:      true,
		ExitCode:      3,
	}
	startTime := time.Unix(90, 789).UTC()
	for _, sample := range samples {
		require.NoError(t, (&SystemMetricsUpdate{
			StartTime: startTime,
			Record:    sample,
		}).Apply(UpdateContext{UseProto: true, MakeRequest: request.Merge}))
	}
	state := FileStreamState{
		MaxRequestSizeBytes: 1 << 20,
		MaxFileLineSize:     1 << 20,
	}
	data, more := state.Pop(request, fs.logger, fs.printer)
	require.False(t, more)
	beforeSend := time.Now()
	require.NoError(t, fs.send(data, make(chan map[string]any, 1)))
	afterSend := time.Now()

	requests := client.GetRequests()
	require.Len(t, requests, 1)
	assert.Equal(t, protoContentType, requests[0].Header.Get("Content-Type"))
	upload := &filestreamv1.FileStreamUpload{}
	require.NoError(t, proto.Unmarshal(requests[0].Body, upload))
	files := make(map[string]*filestreamv1.FileStreamChunk)
	for _, file := range upload.Files {
		files[file.Name] = file
	}
	require.Len(t, files, 3)
	assert.NotContains(t, files, EventsFileName)
	assert.Equal(t, int64(0), files[HistoryFileName].Offset)
	assert.Equal(t, []string{`{"loss":1}`, `{"loss":2}`}, files[HistoryFileName].Content)
	assert.Equal(t, int64(2), files[OutputFileName].Offset)
	assert.Equal(t, []string{"console 1", "console 2"}, files[OutputFileName].Content)
	assert.Equal(t, int64(0), files[SummaryFileName].Offset)
	assert.Equal(t, []string{`{"loss":2}`}, files[SummaryFileName].Content)
	assert.Nil(t, upload.History)
	assert.Equal(t, []string{"model.bin"}, upload.Uploaded)
	require.NotNil(t, upload.Preempting)
	assert.True(t, *upload.Preempting)
	require.NotNil(t, upload.Complete)
	assert.True(t, *upload.Complete)
	require.NotNil(t, upload.ExitCode)
	assert.Equal(t, int32(3), *upload.ExitCode)

	chunk := upload.SystemMetrics
	require.NotNil(t, chunk)
	assert.Equal(t, int64(0), chunk.Offset)
	assert.True(t, proto.Equal(writer, chunk.Writer))
	require.Len(t, chunk.Records, 2)
	require.NotNil(t, chunk.RunStartedAt)
	assert.Equal(t, startTime, chunk.RunStartedAt.AsTime())
	require.NotNil(t, chunk.SentAt)
	assert.False(t, chunk.SentAt.AsTime().Before(beforeSend))
	assert.False(t, chunk.SentAt.AsTime().After(afterSend))
	for i, record := range chunk.Records {
		assert.Nil(t, record.Writer)
		expected := proto.CloneOf(samples[i])
		expected.Writer = nil
		assert.True(t, proto.Equal(expected, record))
	}
}

func TestProtobufLegacyStats(t *testing.T) {
	fs, client := newProtoTestStream(t, map[spb.ServerFeature]bool{
		spb.ServerFeature_TYPED_SYSTEM_METRICS: true,
	})
	request := &FileStreamRequest{}
	require.NoError(t, (&StatsUpdate{
		StartTime: time.Unix(100, 0),
		Record: &spb.StatsRecord{
			Timestamp: timestamppb.New(time.Unix(102, 500_000_000)),
			Item:      []*spb.StatsItem{{Key: "cpu", ValueJson: "25"}},
		},
	}).Apply(UpdateContext{
		UseProto:    true,
		MakeRequest: request.Merge,
		Settings:    fs.settings,
		Logger:      fs.logger,
	}))
	state := FileStreamState{
		MaxRequestSizeBytes: 1 << 20,
		MaxFileLineSize:     1 << 20,
	}
	data, more := state.Pop(request, fs.logger, fs.printer)
	require.False(t, more)
	require.NoError(t, fs.send(data, make(chan map[string]any, 1)))

	requests := client.GetRequests()
	require.Len(t, requests, 1)
	assert.Equal(t, protoContentType, requests[0].Header.Get("Content-Type"))
	upload := &filestreamv1.FileStreamUpload{}
	require.NoError(t, proto.Unmarshal(requests[0].Body, upload))
	assert.Nil(t, upload.SystemMetrics)
	require.Len(t, upload.Files, 1)
	assert.Equal(t, EventsFileName, upload.Files[0].Name)
	assert.Equal(t, int64(0), upload.Files[0].Offset)
	require.Len(t, upload.Files[0].Content, 1)
	assert.JSONEq(t,
		`{"_runtime":2.5,"_timestamp":102.5,"_wandb":true,"system.cpu":25}`,
		upload.Files[0].Content[0])
}

func TestProtobufWriterOverride(t *testing.T) {
	writer := &spb.WriterInfo{Id: "first"}
	other := &spb.WriterInfo{Id: "second"}
	upload := (&FileStreamRequestJSON{SystemMetrics: &filestreamv1.SystemMetricsChunk{
		Records: []*spb.SystemMetricsRecord{{Writer: writer}, {Writer: other}},
	}}).toProto()
	assert.True(t, proto.Equal(writer, upload.SystemMetrics.Writer))
	assert.Nil(t, upload.SystemMetrics.Records[0].Writer)
	assert.True(t, proto.Equal(other, upload.SystemMetrics.Records[1].Writer))
}
