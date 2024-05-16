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

func jsonCompact(t *testing.T, s string) string {
	var buf bytes.Buffer
	assert.NoError(t, json.Compact(&buf, []byte(s)))
	return buf.String()
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

		assert.Len(t, fakeClient.GetRequests(), 2) // 1 batch + 1 final transmission
		req := fakeClient.GetRequests()[0]
		assert.Equal(t, "POST", req.Method)
		assert.Equal(t, "test-url/files/entity/project/run/file_stream", req.URL)
		assert.Equal(t, http.Header{}, req.Header)
		assert.Equal(t,
			jsonCompact(t, `{
				"files": {
					"wandb-history.jsonl": {
						"offset": 0,
						"content": ["{\"test_key\":0}"]
					}
				},
				"uploaded": ["file.txt"]
			}`),
			string(req.Body))
	})

	t.Run("sends heartbeat", func(t *testing.T) {
		fakeHeartbeat := waitingtest.NewFakeStopwatch()
		fs := setup(func() {
			heartbeatStopwatch = fakeHeartbeat
		})

		fakeClient.SetResponse(&apitest.TestResponse{StatusCode: 200}, nil)
		fs.Start("entity", "project", "run", filestream.FileStreamOffsetMap{})
		fakeHeartbeat.SetDone()
		fakeClient.WaitUntilRequestCount(t, 1, time.Hour)
		fs.Close()

		assert.Len(t, fakeClient.GetRequests(), 2) // heartbeat, then final request
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

	t.Run("sends exit code at end", func(t *testing.T) {
		fs := setup(func() {})

		fakeClient.SetResponse(&apitest.TestResponse{StatusCode: 200}, nil)
		fs.Start("entity", "project", "run", filestream.FileStreamOffsetMap{})
		fs.StreamUpdate(&filestream.ExitUpdate{
			Record: &service.RunExitRecord{ExitCode: 345},
		})
		fs.Close()

		assert.Len(t, fakeClient.GetRequests(), 1)
		assert.Equal(t,
			jsonCompact(t, `{
				"complete": true,
				"exitcode": 345
			}`),
			string(fakeClient.GetRequests()[0].Body))
	})

	t.Run("shuts down on HTTP failure", func(t *testing.T) {
		fakeBatchDelay := waitingtest.NewFakeDelay()
		fs := setup(func() {
			processDelay = fakeBatchDelay
		})

		fakeClient.SetResponse(nil, fmt.Errorf("nope!"))
		fs.Start("entity", "project", "run", filestream.FileStreamOffsetMap{})
		fs.StreamUpdate(NewHistoryRecord())              // should go through
		fakeBatchDelay.WaitAndTick(t, true, time.Second) // picks up the chunk
		fs.StreamUpdate(NewHistoryRecord())              // should be ignored
		fs.StreamUpdate(NewHistoryRecord())              // should be ignored
		fs.Close()

		assert.Len(t, fakeClient.GetRequests(), 1)
		messages := printer.Read()
		assert.Len(t, messages, 1)
		assert.Contains(t, messages[0], "Fatal error")
	})
}
