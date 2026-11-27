package filestream

import (
	"bytes"
	"compress/gzip"
	"errors"
	"io"
	"net/http"
	"net/url"
	"sync"
	"testing"
	"time"

	"github.com/hashicorp/go-retryablehttp"
	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"
	"google.golang.org/protobuf/proto"
	"google.golang.org/protobuf/types/known/wrapperspb"

	"github.com/wandb/wandb/core/internal/apitest"
	"github.com/wandb/wandb/core/internal/featurechecker"
	filestreamv1 "github.com/wandb/wandb/core/internal/filestream/proto"
	"github.com/wandb/wandb/core/internal/gqlmock"
	"github.com/wandb/wandb/core/internal/observability"
	"github.com/wandb/wandb/core/internal/observabilitytest"
	"github.com/wandb/wandb/core/internal/settings"
	spb "github.com/wandb/wandb/core/pkg/service_go_proto"
)

func TestStopState_FeedbackTable(t *testing.T) {
	tests := []struct {
		name     string
		feedback []any
		want     bool
	}{
		{"default false", nil, false},
		{"false only -> false", []any{false}, false},
		{"true only -> true", []any{true}, true},
		{"false, non-bool, true -> true", []any{false, true}, true},
		{"true, non-bool, false -> true", []any{true, false}, true},
		{"non-bool ignored", []any{"nope", 1}, false},
	}

	for _, tc := range tests {
		t.Run(tc.name, func(t *testing.T) {
			var fs fileStream
			ch := make(chan map[string]any, len(tc.feedback))
			var wg sync.WaitGroup
			fs.startProcessingFeedback(ch, &wg)

			for _, v := range tc.feedback {
				ch <- map[string]any{"stopped": v}
			}
			close(ch)
			wg.Wait()

			if got := fs.IsStopped(); got != tc.want {
				t.Fatalf("StopState = %v, want %v", got, tc.want)
			}
		})
	}
}

func TestHistoryEncodingNegotiation(t *testing.T) {
	for _, tc := range []struct {
		name        string
		setting     *wrapperspb.StringValue
		features    string
		discoveryOK bool
		lookups     int
		wantProto   bool
	}{
		{name: "default"},
		{name: "explicit JSONL", setting: wrapperspb.String("jsonl")},
		{name: "unknown", setting: wrapperspb.String("bad")},
		{
			name: "enabled", setting: wrapperspb.String("proto+v1"),
			features:    `{"name":"FILESTREAM_PROTO_V1","isEnabled":true}`,
			discoveryOK: true, lookups: 1, wantProto: true,
		},
		{
			name: "disabled", setting: wrapperspb.String("proto+v1"),
			features:    `{"name":"FILESTREAM_PROTO_V1","isEnabled":false}`,
			discoveryOK: true, lookups: 1,
		},
		{
			name: "absent", setting: wrapperspb.String("proto+v1"),
			discoveryOK: true, lookups: 1,
		},
		{name: "lookup error", setting: wrapperspb.String("proto+v1"), lookups: 1},
	} {
		t.Run(tc.name, func(t *testing.T) {
			logger := observabilitytest.NewTestLogger(t)
			server := apitest.NewRecordingServer(apitest.WithHandlerFunc(
				func(w http.ResponseWriter, r *http.Request) {
					_, _ = io.WriteString(w, `{}`)
				},
			))
			defer server.Close()
			baseURL, err := url.Parse(server.URL)
			require.NoError(t, err)
			client := retryablehttp.NewClient()
			client.Logger = nil
			mockGQL := gqlmock.NewMockClient()
			if tc.discoveryOK {
				mockGQL.StubMatchOnce(gqlmock.WithOpName("ServerFeaturesQuery"),
					`{"serverInfo":{"features":[`+tc.features+`]}}`)
			} else {
				mockGQL.StubMatchWithError(gqlmock.WithOpName("ServerFeaturesQuery"),
					errors.New("discovery failed"))
			}
			factory := FileStreamFactory{
				BaseURL:         baseURL,
				FeatureProvider: featurechecker.New(mockGQL, logger),
				Logger:          logger,
				Printer:         observability.NewPrinter(0),
				Settings: settings.From(&spb.Settings{
					XFileStreamHistoryEncoding: tc.setting,
					XFileStreamNoGzip:          wrapperspb.Bool(true),
				}),
			}
			fs := factory.New(client, t.Context(), time.Hour, nil).(*fileStream)
			assert.Empty(t, mockGQL.AllRequests())
			fs.Start("entity", "project", "run", nil)
			defer fs.FinishWithoutExit()

			wantMediaType := "application/json"
			if tc.wantProto {
				wantMediaType = protoContentType
			}
			for range 2 {
				_, mediaType, err := fs.marshalRequest(&FileStreamRequestJSON{})
				require.NoError(t, err)
				assert.Equal(t, wantMediaType, mediaType)
			}
			assert.Len(t, mockGQL.AllRequests(), tc.lookups)
		})
	}
}

func TestSendProtobufHistory(t *testing.T) {
	for _, useGzip := range []bool{false, true} {
		name := "uncompressed"
		if useGzip {
			name = "gzip"
		}
		t.Run(name, func(t *testing.T) {
			server := apitest.NewRecordingServer(apitest.WithHandlerFunc(
				func(w http.ResponseWriter, r *http.Request) {
					_, _ = io.WriteString(w, `{"stopped":true}`)
				},
			))
			defer server.Close()
			baseURL, err := url.Parse(server.URL)
			require.NoError(t, err)
			logger, logs := observabilitytest.NewDebugRecordingTestLogger(t)
			factory := FileStreamFactory{
				BaseURL: baseURL,
				FeatureProvider: featurechecker.NewPreloaded(map[spb.ServerFeature]bool{
					spb.ServerFeature_FILESTREAM_PROTO_V1: true,
					spb.ServerFeature_FILESTREAM_GZIP:     useGzip,
				}),
				Logger:  logger,
				Printer: observability.NewPrinter(0),
				Settings: settings.From(&spb.Settings{
					XFileStreamHistoryEncoding: wrapperspb.String("proto+v1"),
				}),
			}
			client := retryablehttp.NewClient()
			client.Logger = nil
			fs := factory.New(client, t.Context(), time.Hour, nil).(*fileStream)
			fs.Start("entity", "project", "run", nil)
			defer fs.FinishWithoutExit()

			history := &filestreamv1.MetricsBatchChunk{
				Offset:   17,
				RowCount: 2,
				Batch: &filestreamv1.MetricsBatch{
					SeqKey:   "_step",
					Keys:     []string{"private-metric-key"},
					RowEnds:  []uint32{1, 1},
					CellKeys: []uint32{0},
					CellKinds: []filestreamv1.MetricsBatch_Kind{
						filestreamv1.MetricsBatch_KIND_INT,
					},
					Ints: []int64{1},
				},
			}
			data := &FileStreamRequestJSON{TypedHistory: history}
			assert.False(t, data.IsHeartbeat())
			data.Files = map[string]OffsetAndContent{
				EventsFileName:  {Offset: 2, Content: []string{`{"cpu":3}`}},
				OutputFileName:  {Offset: 5, Content: []string{"first", "second"}},
				SummaryFileName: {Offset: 1, Content: []string{`{"accuracy":1}`}},
			}
			data.Uploaded = []string{"model.bin"}
			data.Preempting = proto.Bool(false)
			data.Complete = proto.Bool(true)
			data.ExitCode = proto.Int32(0)

			feedback := make(chan map[string]any, 2)
			require.NoError(t, fs.send(data, feedback))
			require.NoError(t, fs.send(&FileStreamRequestJSON{}, feedback))
			requests := server.Requests()
			fs.FinishWithoutExit()
			assert.Equal(t, map[string]any{"stopped": true}, <-feedback)
			assert.NotContains(t, logs.String(), "private-metric-key")

			require.Len(t, requests, 2)
			for i, request := range requests {
				upload := decodeProtobufRequest(t, request, useGzip)
				if i == 1 {
					assert.True(t, proto.Equal(&filestreamv1.FileStreamUpload{}, upload))
					continue
				}
				assert.True(t, proto.Equal(history, upload.History))
				require.Len(t, upload.Files, len(data.Files))
				for _, chunk := range upload.Files {
					want, ok := data.Files[chunk.Name]
					require.True(t, ok)
					assert.Equal(t, int64(want.Offset), chunk.Offset)
					assert.Equal(t, want.Content, chunk.Content)
				}
				assert.Equal(t, data.Uploaded, upload.Uploaded)
				assert.Equal(t, data.Preempting, upload.Preempting)
				assert.Equal(t, data.Complete, upload.Complete)
				assert.Equal(t, data.ExitCode, upload.ExitCode)
			}
		})
	}
}

func decodeProtobufRequest(
	t *testing.T,
	request apitest.RequestCopy,
	useGzip bool,
) *filestreamv1.FileStreamUpload {
	t.Helper()
	assert.Equal(t, http.MethodPost, request.Method)
	assert.Equal(t, "/files/entity/project/run/file_stream", request.URL.Path)
	assert.Equal(t, protoContentType, request.Header.Get("Content-Type"))
	body := request.Body
	if useGzip {
		assert.Equal(t, "gzip", request.Header.Get("Content-Encoding"))
		reader, err := gzip.NewReader(bytes.NewReader(body))
		require.NoError(t, err)
		body, err = io.ReadAll(reader)
		require.NoError(t, err)
		require.NoError(t, reader.Close())
	} else {
		assert.Empty(t, request.Header.Get("Content-Encoding"))
	}

	upload := &filestreamv1.FileStreamUpload{}
	require.NoError(t, proto.Unmarshal(body, upload))
	return upload
}

func TestMarshalRejectsInvalidTypedHistory(t *testing.T) {
	data := &FileStreamRequestJSON{
		TypedHistory: &filestreamv1.MetricsBatchChunk{},
	}
	fs := &fileStream{}
	_, _, err := fs.marshalRequest(data)
	require.ErrorContains(t, err, "not negotiated")

	fs.typedHistoryEnabled = true
	data.Files = map[string]OffsetAndContent{HistoryFileName: {Content: []string{"{}"}}}
	_, _, err = fs.marshalRequest(data)
	require.ErrorContains(t, err, "both typed and JSONL history")
}
