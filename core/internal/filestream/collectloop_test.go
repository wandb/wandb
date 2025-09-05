package filestream_test

import (
	"testing"
	"time"

	"github.com/stretchr/testify/assert"
	. "github.com/wandb/wandb/core/internal/filestream"
	"github.com/wandb/wandb/core/internal/observability"
	"golang.org/x/time/rate"
)

func TestCollectLoop_BatchesWhileWaiting(t *testing.T) {
	requests := make(chan *FileStreamRequest)
	defer close(requests)
	loop := CollectLoop{
		Logger:            observability.NewNoOpLogger(),
		TransmitRateLimit: rate.NewLimiter(rate.Inf, 1),
	}

	set := func(s string) map[string]struct{} {
		return map[string]struct{}{s: {}}
	}

	transmissions := loop.Start(requests)
	requests <- &FileStreamRequest{UploadedFiles: set("one")}
	requests <- &FileStreamRequest{UploadedFiles: set("two")}
	requests <- &FileStreamRequest{UploadedFiles: set("three")}

	select {
	case result := <-transmissions:
		req := result.GetJSON(&FileStreamState{})
		assert.Len(t, req.Uploaded, 3)
		assert.Contains(t, req.Uploaded, "one")
		assert.Contains(t, req.Uploaded, "two")
		assert.Contains(t, req.Uploaded, "three")
	case <-time.After(time.Second):
		t.Error("timeout after 1 second")
	}
}

func TestCollectLoop_SendsLastRequestImmediately(t *testing.T) {
	requests := make(chan *FileStreamRequest)
	// Use a rate limiter that never lets requests through.
	loop := CollectLoop{
		Logger:            observability.NewNoOpLogger(),
		TransmitRateLimit: &rate.Limiter{},
	}

	transmissions := loop.Start(requests)
	close(requests)

	select {
	case <-transmissions:
	case <-time.After(time.Second):
		t.Error("timeout after 1 second")
	}
}

func TestCollectLoop_BlocksOnceAtMaxSize(t *testing.T) {
	requests := make(chan *FileStreamRequest)
	loop := CollectLoop{
		Logger:              observability.NewNoOpLogger(),
		TransmitRateLimit:   rate.NewLimiter(rate.Inf, 1),
		MaxRequestSizeBytes: 5,
	}

	transmissions := loop.Start(requests)
	requests <- &FileStreamRequest{HistoryLines: []string{`{"x": "12345"}`}}

	// Verify that the loop blocks since the above request is above max size.
	select {
	case requests <- &FileStreamRequest{}:
		t.Error("accepted update beyond max size")
	case <-time.After(10 * time.Millisecond):
	}

	close(requests)

	select {
	case <-transmissions:
	case <-time.After(time.Second):
		t.Error("timeout after 1 second")
	}
}
