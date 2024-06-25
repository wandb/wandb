package filestream_test

import (
	"testing"
	"time"

	"github.com/stretchr/testify/assert"
	"github.com/wandb/wandb/core/internal/filestream"
	"golang.org/x/time/rate"
)

func uploadedFilesUpdate(file string) filestream.BufferMutation {
	return func(buffer *filestream.FileStreamRequestBuffer) {
		buffer.UploadedFiles = append(buffer.UploadedFiles, file)
	}
}

func TestCollectLoop_BatchesWhileWaiting(t *testing.T) {
	mutations := make(chan filestream.BufferMutation)
	defer close(mutations)
	loop := filestream.CollectLoop{TransmitRateLimit: rate.NewLimiter(rate.Inf, 1)}

	transmissions := loop.Start(mutations, filestream.FileStreamOffsetMap{})
	mutations <- uploadedFilesUpdate("one")
	mutations <- uploadedFilesUpdate("two")
	mutations <- uploadedFilesUpdate("three")

	select {
	case result := <-transmissions:
		assert.Equal(t,
			[]string{"one", "two", "three"},
			result.Uploaded)
	case <-time.After(time.Second):
		t.Error("timeout after 1 second")
	}
}

func TestCollectLoop_SendsLastRequestImmediately(t *testing.T) {
	mutations := make(chan filestream.BufferMutation)
	// Use a rate limiter that never lets requests through.
	loop := filestream.CollectLoop{TransmitRateLimit: &rate.Limiter{}}

	transmissions := loop.Start(mutations, filestream.FileStreamOffsetMap{})
	close(mutations)

	select {
	case <-transmissions:
	case <-time.After(time.Second):
		t.Error("timeout after 1 second")
	}
}
