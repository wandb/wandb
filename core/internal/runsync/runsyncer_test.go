package runsync_test

import (
	"testing"
	"time"

	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"
	"golang.org/x/time/rate"
	"google.golang.org/protobuf/proto"
	"google.golang.org/protobuf/types/known/timestamppb"
	"google.golang.org/protobuf/types/known/wrapperspb"

	"github.com/wandb/wandb/core/internal/apitest"
	"github.com/wandb/wandb/core/internal/featurechecker"
	filestreamv1 "github.com/wandb/wandb/core/internal/filestream/proto"
	"github.com/wandb/wandb/core/internal/gqlmock"
	"github.com/wandb/wandb/core/internal/observabilitytest"
	"github.com/wandb/wandb/core/internal/runsync"
	"github.com/wandb/wandb/core/internal/runsyncstate"
	"github.com/wandb/wandb/core/internal/runupsertertest"
	"github.com/wandb/wandb/core/internal/runwork"
	"github.com/wandb/wandb/core/internal/transactionlogtest"
	spb "github.com/wandb/wandb/core/pkg/service_go_proto"
)

func TestSyncPreservesTypedSystemMetrics(t *testing.T) {
	writer := &spb.WriterInfo{Id: "logged-writer", Label: "worker", Hostname: "host"}
	samples := []*spb.SystemMetricsRecord{
		{
			Writer:             writer,
			Sequence:           7,
			Timestamp:          timestamppb.New(time.Unix(100, 123)),
			IntervalMs:         1250,
			SamplingIntervalMs: 1000,
			Host:               &spb.HostMetrics{UptimeS: proto.Float64(25)},
		},
		{
			Writer:             proto.CloneOf(writer),
			Sequence:           12,
			Timestamp:          timestamppb.New(time.Unix(106, 456)),
			IntervalMs:         1100,
			SamplingIntervalMs: 1000,
			DroppedSamples:     4,
			Host:               &spb.HostMetrics{UptimeS: proto.Float64(31)},
		},
	}
	path := transactionlogtest.WandbFile(t,
		&spb.Record{RecordType: &spb.Record_Run{Run: &spb.RunRecord{
			Entity:    "entity",
			Project:   "project",
			RunId:     "run",
			StartTime: timestamppb.New(time.Unix(90, 0)),
		}}},
		&spb.Record{RecordType: &spb.Record_SystemMetrics{SystemMetrics: samples[0]}},
		&spb.Record{RecordType: &spb.Record_SystemMetrics{SystemMetrics: samples[1]}},
		exitRecord(0),
	)
	settings := runsync.MakeSyncSettings(&spb.Settings{
		BaseUrl:            wrapperspb.String("https://api.wandb.test"),
		ApiKey:             wrapperspb.String("test-api-key"),
		Console:            wrapperspb.String("off"),
		DisableJobCreation: wrapperspb.Bool(true),
	}, path)
	logger := observabilitytest.NewTestLogger(t)
	factory := runsync.InjectRunSyncerFactory(settings, logger)
	features := featurechecker.NewPreloaded(map[spb.ServerFeature]bool{
		spb.ServerFeature_TYPED_SYSTEM_METRICS: true,
	})
	mockGQL := gqlmock.NewMockClient()
	runupsertertest.StubUpsertBucket(t, mockGQL)
	runupsertertest.StubUpsertBucket(t, mockGQL)
	factory.RecordParserFactory.FeatureProvider = features
	factory.RecordParserFactory.GraphqlClientOrNil = mockGQL
	factory.RecordParserFactory.ClientID = "sync-client"
	factory.SenderFactory.FeatureProvider = features
	factory.SenderFactory.GraphqlClient = mockGQL
	factory.SenderFactory.RunfilesUploaderFactory.GraphQL = mockGQL
	factory.SenderFactory.FileStreamFactory.FeatureProvider = features
	client := apitest.NewFakeClient("https://api.wandb.test")
	client.SetResponse(&apitest.TestResponse{StatusCode: 200}, nil)
	work := runwork.New(32, logger)
	fileStream := factory.SenderFactory.FileStreamFactory.New(
		client, work.BeforeEndCtx(), time.Hour, rate.NewLimiter(rate.Inf, 1))
	sender := factory.SenderFactory.NewWithFileStream(work, fileStream)
	tbHandler := factory.TBHandlerFactory.New(work, time.Second)
	parser := factory.RecordParserFactory.New(
		work.BeforeEndCtx(), tbHandler, runsyncstate.File(path))
	reader := factory.RunReaderFactory.New(
		path, runsync.ToDisplayPath(path, ""), nil, false, parser, work)
	senderDone := make(chan struct{})
	go func() {
		defer close(senderDone)
		sender.Do(work.Chan())
	}()
	require.NoError(t, reader.ProcessTransactionLog(t.Context()))
	<-senderDone

	var uploaded []*spb.SystemMetricsRecord
	for _, request := range client.GetRequests() {
		assert.Equal(t, "application/vnd.wandb.filestream.proto+v1",
			request.Header.Get("Content-Type"))
		var upload filestreamv1.FileStreamUpload
		require.NoError(t, proto.Unmarshal(request.Body, &upload))
		chunk := upload.GetSystemMetrics()
		if chunk == nil {
			continue
		}
		assert.EqualValues(t, len(uploaded), chunk.Offset)
		assert.True(t, proto.Equal(writer, chunk.Writer))
		for _, sample := range chunk.Records {
			assert.Nil(t, sample.Writer)
			sample.Writer = proto.CloneOf(chunk.Writer)
			uploaded = append(uploaded, sample)
		}
	}
	require.Len(t, uploaded, len(samples))
	for i, sample := range samples {
		assert.True(t, proto.Equal(sample, uploaded[i]),
			"sample %d changed: got %v, want %v", i, uploaded[i], sample)
	}
}
