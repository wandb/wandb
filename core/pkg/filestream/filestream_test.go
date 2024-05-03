package filestream_test

import (
	"bytes"
	"encoding/json"
	"fmt"
	"net/http"
	"time"

	"github.com/wandb/wandb/core/internal/apitest"
	"github.com/wandb/wandb/core/internal/waiting"
	"github.com/wandb/wandb/core/internal/waitingtest"

	"github.com/wandb/wandb/core/pkg/filestream"
	"github.com/wandb/wandb/core/pkg/observability"

	"testing"

	"github.com/stretchr/testify/assert"
	"github.com/wandb/wandb/core/pkg/service"
)

func NewHistoryRecord() filestream.Update {
	return &filestream.HistoryUpdate{
		Record: &service.HistoryRecord{
			Step: &service.HistoryStep{Num: 0},
			Item: []*service.HistoryItem{
				{Key: "test_key", ValueJson: fmt.Sprintf("%f", 0.0)},
			},
		},
	}
}

func TestFileStream(t *testing.T) {
	var fakeClient *apitest.FakeClient
	var printer *observability.Printer
	var heartbeatStopwatch waiting.Stopwatch
	var processDelay waiting.Delay

	setup := func(configure func()) filestream.FileStream {
		fakeClient = apitest.NewFakeClient("test-url")
		printer = observability.NewPrinter()
		// By default, chunk everything and prevent heartbeats.
		heartbeatStopwatch = waitingtest.NewFakeStopwatch()
		processDelay = waitingtest.NewFakeDelay()

		// Allow tests to override the above objects.
		configure()

		return filestream.NewFileStream(filestream.FileStreamParams{
			Settings:           &service.Settings{},
			Logger:             observability.NewNoOpLogger(),
			Printer:            printer,
			ApiClient:          fakeClient,
			DelayProcess:       processDelay,
			HeartbeatStopwatch: heartbeatStopwatch,
		})
	}

	t.Run("batches and sends", func(t *testing.T) {
		fs := setup(func() {})

		fs.Start("entity", "project", "run", filestream.FileStreamOffsetMap{})
		fakeClient.SetResponse(&apitest.TestResponse{StatusCode: 200}, nil)
		fs.StreamUpdate(NewHistoryRecord())
		fs.StreamUpdate(&filestream.FilesUploadedUpdate{RelativePath: "file.txt"})
		fs.Close()

		assert.Len(t, fakeClient.GetRequests(), 1)
		req := fakeClient.GetRequests()[0]
		assert.Equal(t, "POST", req.Method)
		assert.Equal(t, "test-url/files/entity/project/run/file_stream", req.URL)
		assert.Equal(t, http.Header{}, req.Header)
		var expected bytes.Buffer
		assert.NoError(t, json.Compact(&expected,
			[]byte(`{
				"files": {
					"wandb-history.jsonl": {
						"offset": 0,
						"content": ["{\"test_key\":0}"]
					}
				},
				"uploaded": ["file.txt"]
			}`)))
		assert.Equal(t, expected.String(), string(req.Body))
	})

	t.Run("sends heartbeat", func(t *testing.T) {
		fakeHeartbeat := waitingtest.NewFakeStopwatch()
		fs := setup(func() {
			heartbeatStopwatch = fakeHeartbeat
		})

		fakeClient.SetResponse(&apitest.TestResponse{StatusCode: 200}, nil)
		fakeHeartbeat.SetDone()
		fs.Start("entity", "project", "run", filestream.FileStreamOffsetMap{})
		// We're relying on a single loop happening in-between. Technically
		// this test is brittle: the code would still be correct if Close()
		// pre-empted Start().
		fs.Close()

		assert.Len(t, fakeClient.GetRequests(), 1)
		assert.Equal(t,
			apitest.RequestCopy{
				Method: "POST",
				URL:    "test-url/files/entity/project/run/file_stream",
				Header: http.Header{},
				Body:   []byte("{}"),
			},
			fakeClient.GetRequests()[0],
		)
	})

	t.Run("shuts down on HTTP failure", func(t *testing.T) {
		fakeBatchDelay := waitingtest.NewFakeDelay()
		fs := setup(func() {
			processDelay = fakeBatchDelay
		})

		fakeClient.SetResponse(nil, fmt.Errorf("nope!"))
		fs.Start("entity", "project", "run", filestream.FileStreamOffsetMap{})
		fs.StreamUpdate(NewHistoryRecord())           // should go through
		fakeBatchDelay.WaitAndTick(true, time.Second) // picks up the chunk
		fs.StreamUpdate(NewHistoryRecord())           // should be ignored
		fs.StreamUpdate(NewHistoryRecord())           // should be ignored
		fs.Close()

		assert.Len(t, fakeClient.GetRequests(), 1)
		messages := printer.Read()
		assert.Len(t, messages, 1)
		assert.Contains(t, messages[0], "Fatal error")
	})
}
