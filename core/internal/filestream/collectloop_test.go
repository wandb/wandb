package filestream_test

import (
	"testing"
	"time"

	"github.com/stretchr/testify/assert"
	. "github.com/wandb/wandb/core/internal/filestream"
	"golang.org/x/time/rate"
)

func TestCollectLoop_BatchesWhileWaiting(t *testing.T) {
	requests := make(chan *FileStreamRequest)
	defer close(requests)
	loop := CollectLoop{TransmitRateLimit: rate.NewLimiter(rate.Inf, 1)}

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
	loop := CollectLoop{TransmitRateLimit: &rate.Limiter{}}

	transmissions := loop.Start(requests)
	close(requests)

	select {
	case <-transmissions:
	case <-time.After(time.Second):
		t.Error("timeout after 1 second")
	}
}
