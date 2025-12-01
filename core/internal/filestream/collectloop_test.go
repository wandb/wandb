package filestream_test

import (
	"testing"
	"time"

	"github.com/stretchr/testify/assert"
	. "github.com/wandb/wandb/core/internal/filestream"
	"github.com/wandb/wandb/core/internal/observability"
	"github.com/wandb/wandb/core/internal/waiting"
	"golang.org/x/time/rate"
)

func TestCollectLoop_BatchesWhileWaiting(t *testing.T) {
	requests := make(chan *FileStreamRequest)
	defer close(requests)
	loop := CollectLoop{
		Logger:            observability.NewNoOpLogger(),
		Printer:           observability.NewPrinter(),
		TransmitRateLimit: rate.NewLimiter(rate.Inf, 1),
	}
	state := &FileStreamState{MaxRequestSizeBytes: 99999}

	set := func(s string) map[string]struct{} {
		return map[string]struct{}{s: {}}
	}

	transmissions := loop.Start(state, requests)
	requests <- &FileStreamRequest{UploadedFiles: set("one")}
	requests <- &FileStreamRequest{UploadedFiles: set("two")}
	requests <- &FileStreamRequest{UploadedFiles: set("three")}

	req, _ := transmissions.NextRequest(waiting.NewStopwatch(time.Second))
	transmissions.IgnoreFutureRequests()

	assert.Len(t, req.Uploaded, 3)
	assert.Contains(t, req.Uploaded, "one")
	assert.Contains(t, req.Uploaded, "two")
	assert.Contains(t, req.Uploaded, "three")
}

func TestCollectLoop_SendsLastRequestImmediately(t *testing.T) {
	requests := make(chan *FileStreamRequest)
	// Use a rate limiter that never lets requests through.
	loop := CollectLoop{
		Logger:            observability.NewNoOpLogger(),
		Printer:           observability.NewPrinter(),
		TransmitRateLimit: &rate.Limiter{},
	}
	state := &FileStreamState{MaxRequestSizeBytes: 99999}

	transmissions := loop.Start(state, requests)
	close(requests)
	request1, ok1 := transmissions.NextRequest(waiting.NewStopwatch(time.Second))
	request2, ok2 := transmissions.NextRequest(waiting.NewStopwatch(time.Second))

	assert.True(t, ok1)
	assert.NotNil(t, request1)
	assert.False(t, ok2)
	assert.Nil(t, request2)
}

func TestCollectLoop_BlocksOnceAtMaxSize(t *testing.T) {
	requests := make(chan *FileStreamRequest)
	loop := CollectLoop{
		Logger:            observability.NewNoOpLogger(),
		Printer:           observability.NewPrinter(),
		TransmitRateLimit: rate.NewLimiter(rate.Inf, 1),
	}
	state := &FileStreamState{MaxRequestSizeBytes: 5}

	transmissions := loop.Start(state, requests)
	requests <- &FileStreamRequest{HistoryLines: []string{`{"x": "12345"}`}}

	// Verify that the loop blocks since the above request is above max size.
	select {
	case requests <- &FileStreamRequest{}:
		t.Error("accepted update beyond max size")
	case <-time.After(10 * time.Millisecond):
	}

	close(requests)
	transmissions.IgnoreFutureRequests()
}
