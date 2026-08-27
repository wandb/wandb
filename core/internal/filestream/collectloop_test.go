package filestream_test

import (
	"testing"
	"time"

	"github.com/stretchr/testify/assert"
	"golang.org/x/time/rate"

	. "github.com/wandb/wandb/core/internal/filestream"
	"github.com/wandb/wandb/core/internal/observability"
)

func TestCollectLoop_BatchesWhileWaiting(t *testing.T) {
	requests := make(chan *FileStreamRequest)
	defer close(requests)
	loop := CollectLoop{
		Logger:            observability.NewNoOpLogger(),
		Printer:           observability.NewPrinter(0),
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

	req, _ := transmissions.NextRequest(make(<-chan time.Time))
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
		Printer:           observability.NewPrinter(0),
		TransmitRateLimit: &rate.Limiter{},
	}
	state := &FileStreamState{MaxRequestSizeBytes: 99999}

	transmissions := loop.Start(state, requests)
	close(requests)
	request1, ok1 := transmissions.NextRequest(make(<-chan time.Time))
	request2, ok2 := transmissions.NextRequest(make(<-chan time.Time))

	assert.True(t, ok1)
	assert.NotNil(t, request1)
	assert.False(t, ok2)
	assert.Nil(t, request2)
}

func TestCollectLoop_AppliesNewRateLimitToPendingBatch(t *testing.T) {
	requests := make(chan *FileStreamRequest)
	defer close(requests)
	limiter := rate.NewLimiter(rate.Every(time.Hour), 1)
	loop := CollectLoop{
		Logger:            observability.NewNoOpLogger(),
		Printer:           observability.NewPrinter(0),
		TransmitRateLimit: limiter,
	}
	state := &FileStreamState{MaxRequestSizeBytes: 99999}
	noHeartbeat := make(<-chan time.Time)

	transmissions := loop.Start(state, requests)

	// The first request is sent immediately, emptying the token bucket,
	// so that the next batch reserves a transmission an hour out.
	requests <- &FileStreamRequest{UploadedFiles: map[string]struct{}{"one": {}}}
	_, ok := transmissions.NextRequest(noHeartbeat)
	assert.True(t, ok)
	requests <- &FileStreamRequest{UploadedFiles: map[string]struct{}{"two": {}}}
	time.Sleep(10 * time.Millisecond)

	// Speeding up the limiter (as the transmit ramp does) must apply to
	// the pending batch when more data is merged into it.
	limiter.SetLimit(rate.Every(time.Millisecond))
	requests <- &FileStreamRequest{HistoryLines: []string{"{}"}}

	released := make(chan struct{})
	go func() {
		_, _ = transmissions.NextRequest(noHeartbeat)
		close(released)
	}()
	select {
	case <-released:
	case <-time.After(5 * time.Second):
		t.Error("pending batch not released after the rate limit sped up")
	}
	transmissions.IgnoreFutureRequests()
}

func TestCollectLoop_BlocksOnceAtMaxSize(t *testing.T) {
	requests := make(chan *FileStreamRequest)
	loop := CollectLoop{
		Logger:            observability.NewNoOpLogger(),
		Printer:           observability.NewPrinter(0),
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
