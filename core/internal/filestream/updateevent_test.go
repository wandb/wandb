package filestream_test

import (
	"context"
	"encoding/json"
	"io"
	"math"
	"net/http"
	"net/http/httptest"
	"net/url"
	"testing"
	"time"

	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"
	"golang.org/x/time/rate"
	"google.golang.org/protobuf/proto"

	"github.com/wandb/wandb/core/internal/api"
	"github.com/wandb/wandb/core/internal/featurechecker"
	. "github.com/wandb/wandb/core/internal/filestream"
	"github.com/wandb/wandb/core/internal/observability"
	"github.com/wandb/wandb/core/internal/observabilitytest"
	"github.com/wandb/wandb/core/internal/settings"
	spb "github.com/wandb/wandb/core/pkg/service_go_proto"
)

func TestEventUpdate_JSON(t *testing.T) {
	for _, metric := range []bool{false, true} {
		t.Run(map[bool]string{false: "no metric", true: "zero metric"}[metric], func(t *testing.T) {
			event := &spb.EventRecord{
				EventId: "stable-id", TimestampMs: 1234,
				Type: "checkpoint", Title: "Saved", Severity: "INFO", Step: proto.Int64(0),
				Attributes: map[string]*spb.EventAttributeValue{
					"name": {
						Value: &spb.EventAttributeValue_StringValue{StringValue: "model"},
					},
					"count": {
						Value: &spb.EventAttributeValue_IntValue{IntValue: math.MinInt64},
					},
					"score": {
						Value: &spb.EventAttributeValue_DoubleValue{DoubleValue: 4.2e9},
					},
					"negative_zero": {
						Value: &spb.EventAttributeValue_DoubleValue{
							DoubleValue: math.Copysign(0, -1),
						},
					},
					"saved": {Value: &spb.EventAttributeValue_BoolValue{BoolValue: false}},
				},
			}
			metricJSON := ""
			if metric {
				event.StepMetric = "tokens"
				event.StepMetricValue = proto.Float64(0)
				metricJSON = `,"step_metric":"tokens","step_metric_value":0`
			}
			var request *FileStreamRequest
			require.NoError(t, (&EventUpdate{Record: event}).Apply(UpdateContext{
				MakeRequest: func(r *FileStreamRequest) { request = r },
			}))
			require.NotNil(t, request)
			chunk, more := pop(t, &FileStreamState{MaxRequestSizeBytes: 10000}, request)
			assert.False(t, more)
			assert.False(t, chunk.IsHeartbeat())
			data, err := json.Marshal(chunk)
			require.NoError(t, err)
			assert.JSONEq(t, `{"events":[{
				"event_id":"stable-id","timestamp_ms":1234,"type":"checkpoint",
				"title":"Saved","severity":"INFO","step":0,
				"attributes":{
					"name":{"type":"string","value":"model"},
					"count":{"type":"int64","value":"-9223372036854775808"},
					"score":{"type":"float64","value":"4.2e+09"},
					"negative_zero":{"type":"float64","value":"-0"},
					"saved":{"type":"bool","value":"false"}
				}`+metricJSON+`}]}`, string(data))
		})
	}
}

func TestRunEvents_MergeAndSplit(t *testing.T) {
	first := json.RawMessage(`{"event_id":"first"}`)
	second := json.RawMessage(`{"event_id":"second"}`)
	request := &FileStreamRequest{
		HistoryLines: []string{"history"},
		EventsLines:  []string{"system"},
		Events:       []json.RawMessage{first},
	}
	request.Merge(&FileStreamRequest{Events: []json.RawMessage{second}, Complete: true})
	require.Equal(t, []json.RawMessage{first, second}, request.Events)
	state := &FileStreamState{MaxRequestSizeBytes: 1}
	assert.True(t, state.IsAtSizeLimit(&FileStreamRequest{Events: request.Events}))
	var chunks []*FileStreamRequestJSON
	for more := true; more; {
		var chunk *FileStreamRequestJSON
		chunk, more = pop(t, state, request)
		chunks = append(chunks, chunk)
		require.LessOrEqual(t, len(chunks), 4)
		if more {
			assert.Nil(t, chunk.Complete)
		}
	}
	require.Len(t, chunks, 4)
	assert.Equal(t, []string{"history"}, chunks[0].Files[HistoryFileName].Content)
	assert.Equal(t, []string{"system"}, chunks[1].Files[EventsFileName].Content)
	assert.Equal(t, []json.RawMessage{first}, chunks[2].Events)
	assert.Equal(t, []json.RawMessage{second}, chunks[3].Events)
	require.NotNil(t, chunks[3].Complete)
	assert.True(t, *chunks[3].Complete)
	assert.Empty(t, request.Events)
	chunk, more := pop(t, state, request)
	assert.False(t, more)
	assert.Empty(t, chunk.Events)
}

func TestRunEvents_BeforeStartAndRetry(t *testing.T) {
	var bodies [][]byte
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		assert.Equal(t, "/files/entity/project/run/file_stream", r.URL.Path)
		body, err := io.ReadAll(r.Body)
		assert.NoError(t, err)
		bodies = append(bodies, body)
		if len(bodies) == 1 {
			w.WriteHeader(http.StatusServiceUnavailable)
		} else {
			_, _ = w.Write([]byte("{}"))
		}
	}))
	defer server.Close()
	baseURL, err := url.Parse(server.URL)
	require.NoError(t, err)
	logger := observabilitytest.NewTestLogger(t)
	printer := observability.NewPrinter(0)
	defer printer.Close()
	factory := &FileStreamFactory{
		BaseURL: baseURL, Settings: settings.From(&spb.Settings{}),
		Logger: logger, Printer: printer, FeatureProvider: featurechecker.New(nil, logger),
	}
	ctx, cancel := context.WithTimeout(context.Background(), 5*time.Second)
	defer cancel()
	fs := factory.New(api.NewClient(api.ClientOptions{
		RetryMax: 1, RetryWaitMin: time.Nanosecond, RetryWaitMax: time.Nanosecond,
	}), ctx, time.Hour, rate.NewLimiter(rate.Inf, 1))
	fs.StreamUpdate(&EventUpdate{Record: &spb.EventRecord{EventId: "first"}})
	fs.StreamUpdate(&EventUpdate{Record: &spb.EventRecord{EventId: "second"}})
	fs.Start("entity", "project", "run", nil)
	fs.FinishWithoutExit()

	require.GreaterOrEqual(t, len(bodies), 2)
	assert.Equal(t, bodies[0], bodies[1])
	var ids []string
	for _, body := range bodies[1:] {
		var request struct {
			Events []struct {
				ID string `json:"event_id"`
			} `json:"events"`
		}
		require.NoError(t, json.Unmarshal(body, &request))
		for _, event := range request.Events {
			ids = append(ids, event.ID)
		}
	}
	assert.Equal(t, []string{"first", "second"}, ids)
}

func TestEventUpdate_EmptyMetricName(t *testing.T) {
	var request *FileStreamRequest
	require.NoError(t, (&EventUpdate{Record: &spb.EventRecord{
		StepMetricValue: proto.Float64(0),
	}}).Apply(UpdateContext{
		MakeRequest: func(r *FileStreamRequest) { request = r },
	}))
	require.NotNil(t, request)
	require.Len(t, request.Events, 1)
	assert.JSONEq(t, `{
		"event_id":"","timestamp_ms":0,"type":"","title":"","severity":"","step":0,
		"step_metric":"","step_metric_value":0,"attributes":{}
	}`, string(request.Events[0]))
}
