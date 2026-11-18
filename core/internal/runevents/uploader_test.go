package runevents_test

import (
	"bytes"
	"context"
	"encoding/json"
	"io"
	"net/http"
	"net/http/httptest"
	"net/url"
	"strconv"
	"strings"
	"sync"
	"sync/atomic"
	"testing"
	"time"

	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"
	"google.golang.org/protobuf/proto"

	"github.com/wandb/wandb/core/internal/api"
	"github.com/wandb/wandb/core/internal/observability"
	"github.com/wandb/wandb/core/internal/observabilitytest"
	"github.com/wandb/wandb/core/internal/runevents"
	spb "github.com/wandb/wandb/core/pkg/service_go_proto"
)

func newUploader(
	t *testing.T,
	handler http.HandlerFunc,
) (*runevents.Uploader, *observability.Printer, *bytes.Buffer) {
	t.Helper()
	server := httptest.NewServer(handler)
	t.Cleanup(server.Close)
	baseURL, err := url.Parse(server.URL)
	require.NoError(t, err)
	logger, entries := observabilitytest.NewRecordingTestLogger(t)
	printer := observability.NewPrinter(10)
	uploader := runevents.New(t.Context(), runevents.Params{
		BaseURL: baseURL,
		Project: "team/project",
		RunID:   "run123",
		Logger:  logger,
		Printer: printer,
		HTTPOptions: api.ClientOptions{
			RetryWaitMin: time.Millisecond,
			RetryWaitMax: time.Millisecond,
		},
	})
	t.Cleanup(uploader.Finish)
	return uploader, printer, entries
}

func TestUploaderFlushesPendingEventOnceOnConcurrentFinish(t *testing.T) {
	requests := make(chan string, 3)
	uploader, _, _ := newUploader(t, func(w http.ResponseWriter, r *http.Request) {
		assert.Equal(t, http.MethodPost, r.Method)
		assert.Equal(t, "/logs/ingest", r.URL.Path)
		assert.Equal(t, "application/json", r.Header.Get("Content-Type"))
		body, err := io.ReadAll(r.Body)
		assert.NoError(t, err)
		requests <- string(body)
		w.WriteHeader(http.StatusAccepted)
	})

	uploader.Enqueue(&spb.EventRecord{
		EventId:         "event-1",
		Type:            "dataset_switch",
		Title:           "Switched data",
		Step:            proto.Int64(42),
		Severity:        "WARN",
		TimestampMs:     1700000000123,
		StepMetric:      "tokens_seen",
		StepMetricValue: proto.Float64(4.2e9),
		Attributes: map[string]*spb.EventAttributeValue{
			"dataset": {Value: &spb.EventAttributeValue_StringValue{StringValue: ""}},
			"shards":  {Value: &spb.EventAttributeValue_IntValue{IntValue: -3}},
			"rate":    {Value: &spb.EventAttributeValue_DoubleValue{DoubleValue: 0.25}},
			"ok":      {Value: &spb.EventAttributeValue_BoolValue{BoolValue: false}},
		},
	})
	var finish sync.WaitGroup
	finish.Go(uploader.Finish)
	finish.Go(uploader.Finish)
	finish.Wait()

	require.Len(t, requests, 1)
	body := <-requests
	assert.Contains(t, body, `"timestamp":1700000000123000000`)
	assert.JSONEq(t, `{
		"project": "team/project",
		"records": [{
			"event_id": "event-1",
			"run": "run123",
			"timestamp": 1700000000123000000,
			"message": "Switched data",
			"attributes": {
				"step": {"type":"int64","value":"42"},
				"severity": {"type":"string","value":"WARN"},
				"event_type": {"type":"string","value":"dataset_switch"},
				"source_sdk": {"type":"string","value":"wandb-python"},
				"step_metric": {"type":"string","value":"tokens_seen"},
				"step_metric_value": {"type":"float64","value":"4.2e+09"},
				"dataset": {"type":"string","value":""},
				"shards": {"type":"int64","value":"-3"},
				"rate": {"type":"float64","value":"0.25"},
				"ok": {"type":"bool","value":"false"}
			}
		}]
	}`, body)
}

func TestUploaderFlushesPartialBatchWhileRunning(t *testing.T) {
	received := make(chan struct{}, 1)
	uploader, _, _ := newUploader(t, func(w http.ResponseWriter, _ *http.Request) {
		received <- struct{}{}
		w.WriteHeader(http.StatusAccepted)
	})
	uploader.Enqueue(&spb.EventRecord{EventId: "event-1"})

	select {
	case <-received:
	case <-time.After(5 * time.Second):
		t.Fatal("partial batch was not uploaded while the run was active")
	}
}

func TestUploaderBatchLimits(t *testing.T) {
	for _, tc := range []struct {
		name       string
		title      string
		total      int
		firstBatch int
	}{
		{name: "record count", title: "checkpoint", total: 101, firstBatch: 100},
		{name: "encoded bytes", title: strings.Repeat("\x00", 4096), total: 42, firstBatch: 21},
	} {
		t.Run(tc.name, func(t *testing.T) {
			batchSizes := make(chan int, 3)
			uploader, _, _ := newUploader(t, func(w http.ResponseWriter, r *http.Request) {
				body, err := io.ReadAll(r.Body)
				assert.NoError(t, err)
				assert.LessOrEqual(t, len(body), 512*1024)

				var batch struct {
					Records []json.RawMessage
				}
				assert.NoError(t, json.Unmarshal(body, &batch))
				batchSizes <- len(batch.Records)
				w.WriteHeader(http.StatusAccepted)
			})

			for i := range tc.total {
				uploader.Enqueue(&spb.EventRecord{EventId: strconv.Itoa(i), Title: tc.title})
			}
			select {
			case size := <-batchSizes:
				assert.Equal(t, tc.firstBatch, size)
			case <-time.After(time.Second):
				t.Fatal("full batch was not uploaded immediately")
			}
			uploader.Finish()
			require.Len(t, batchSizes, 1)
			assert.Equal(t, tc.total-tc.firstBatch, <-batchSizes)
		})
	}
}

func TestUploaderRetriesWithSamePayload(t *testing.T) {
	for _, status := range []int{
		http.StatusTooManyRequests,
		http.StatusNotImplemented,
		http.StatusServiceUnavailable,
		http.StatusGatewayTimeout,
	} {
		t.Run(strconv.Itoa(status), func(t *testing.T) {
			requests := make(chan string, 3)
			uploader, _, _ := newUploader(t, func(w http.ResponseWriter, r *http.Request) {
				body, err := io.ReadAll(r.Body)
				assert.NoError(t, err)
				requests <- string(body)
				if len(requests) == 1 {
					w.WriteHeader(status)
					return
				}
				w.WriteHeader(http.StatusAccepted)
			})
			uploader.Enqueue(&spb.EventRecord{EventId: "stable-id"})
			uploader.Finish()

			require.Len(t, requests, 2)
			first := <-requests
			assert.Contains(t, first, `"event_id":"stable-id"`)
			assert.Equal(t, first, <-requests)
		})
	}
}

func TestUploaderDropsRejectedBatch(t *testing.T) {
	for _, status := range []int{http.StatusBadRequest, http.StatusRequestEntityTooLarge} {
		t.Run(strconv.Itoa(status), func(t *testing.T) {
			var calls atomic.Int32
			uploader, printer, logs := newUploader(t, func(w http.ResponseWriter, _ *http.Request) {
				if calls.Add(1) == 1 {
					w.WriteHeader(status)
					return
				}
				w.WriteHeader(http.StatusAccepted)
			})
			for i := range 101 {
				uploader.Enqueue(&spb.EventRecord{EventId: strconv.Itoa(i)})
			}
			uploader.Finish()

			assert.EqualValues(t, 2, calls.Load())
			assert.Contains(t, logs.String(), "runevents: dropped event batch")
			assert.Empty(t, printer.Read())
		})
	}
}

func TestUploaderDisablesAfterUnavailableResponse(t *testing.T) {
	for _, status := range []int{http.StatusUnauthorized, http.StatusForbidden, http.StatusNotFound} {
		t.Run(strconv.Itoa(status), func(t *testing.T) {
			var calls atomic.Int32
			uploader, printer, _ := newUploader(t, func(w http.ResponseWriter, _ *http.Request) {
				calls.Add(1)
				w.WriteHeader(status)
			})
			for i := range 101 {
				uploader.Enqueue(&spb.EventRecord{EventId: strconv.Itoa(i)})
			}

			ctx, cancel := context.WithTimeout(t.Context(), time.Second)
			defer cancel()
			warnings := printer.ReadWait(ctx)
			require.Len(t, warnings, 1)
			assert.Equal(t, observability.Warning, warnings[0].Severity)
			assert.Contains(t, warnings[0].Content, "Event logging is disabled for this project")
			uploader.Enqueue(&spb.EventRecord{EventId: "after-disable"})
			uploader.Finish()

			assert.EqualValues(t, 1, calls.Load())
			assert.Empty(t, printer.Read())
		})
	}
}

func TestUploaderDropsNewestWhenQueueIsFull(t *testing.T) {
	started := make(chan struct{}, 1)
	unblock := make(chan struct{})
	var count atomic.Int32
	uploader, printer, _ := newUploader(t, func(w http.ResponseWriter, r *http.Request) {
		var batch struct {
			Records []struct {
				ID string `json:"event_id"`
			}
		}
		assert.NoError(t, json.NewDecoder(r.Body).Decode(&batch))
		for _, event := range batch.Records {
			assert.NotEqual(t, "newest-dropped", event.ID)
		}
		if count.Add(int32(len(batch.Records))) == 100 {
			started <- struct{}{}
			select {
			case <-unblock:
			case <-t.Context().Done():
			}
		}
		w.WriteHeader(http.StatusAccepted)
	})
	defer func() {
		close(unblock)
		uploader.Finish()
		assert.EqualValues(t, 10000, count.Load())
	}()
	for i := range 100 {
		uploader.Enqueue(&spb.EventRecord{EventId: strconv.Itoa(i)})
	}
	select {
	case <-started:
	case <-time.After(time.Second):
		t.Fatal("first batch was not uploaded")
	}
	for range 9900 {
		uploader.Enqueue(&spb.EventRecord{EventId: "queued"})
	}
	for range 2 {
		uploader.Enqueue(&spb.EventRecord{EventId: "newest-dropped"})
	}
	warnings := printer.Read()
	require.Len(t, warnings, 1)
	assert.Equal(t, observability.Warning, warnings[0].Severity)
	assert.Contains(t, warnings[0].Content, "queue is full")
}
