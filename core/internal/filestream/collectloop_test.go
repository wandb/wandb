package filestream_test

import (
	"testing"
	"testing/synctest"
	"time"

	"github.com/stretchr/testify/assert"
	"github.com/stretchr/testify/require"

	. "github.com/wandb/wandb/core/internal/filestream"
	"github.com/wandb/wandb/core/internal/observability"
)

func TestCollectLoop_BatchesWhileWaiting(t *testing.T) {
	requests := make(chan *FileStreamRequest)
	defer close(requests)
	loop := CollectLoop{
		Logger:  observability.NewNoOpLogger(),
		Printer: observability.NewPrinter(0),
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
	loop := CollectLoop{
		Logger:  observability.NewNoOpLogger(),
		Printer: observability.NewPrinter(0),
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

// startRampLoop starts a collect loop with a 15-second transmit interval
// inside a synctest bubble.
//
// It returns the loop's request channel and a function that waits for the
// next transmission and returns the time since the loop started.
func startRampLoop(
	t *testing.T,
	initialTransmitInterval time.Duration,
) (chan<- *FileStreamRequest, func() time.Duration) {
	requests := make(chan *FileStreamRequest)
	loop := CollectLoop{
		Logger:                  observability.NewNoOpLogger(),
		Printer:                 observability.NewPrinter(0),
		TransmitInterval:        15 * time.Second,
		InitialTransmitInterval: initialTransmitInterval,
	}
	t.Cleanup(loop.Printer.Close)
	state := &FileStreamState{MaxRequestSizeBytes: 99999}

	transmissions := loop.Start(state, requests)
	start := time.Now()

	return requests, func() time.Duration {
		_, ok := transmissions.NextRequest(make(<-chan time.Time))
		require.True(t, ok)
		return time.Since(start)
	}
}

func TestCollectLoop_RampsAfterFirstHistory(t *testing.T) {
	synctest.Test(t, func(t *testing.T) {
		requests, sent := startRampLoop(t, 2*time.Second)

		// The first history is sent immediately, and the interval then
		// doubles after each transmission until it is back at 15 seconds.
		var sentAt []time.Duration
		for range 5 {
			requests <- &FileStreamRequest{HistoryLines: []string{"{}"}}
			sentAt = append(sentAt, sent())
		}
		close(requests)

		assert.Equal(t,
			[]time.Duration{
				0,
				2 * time.Second,
				6 * time.Second,
				14 * time.Second,
				29 * time.Second,
			},
			sentAt)
	})
}

func TestCollectLoop_RampSpeedsUpPendingBatch(t *testing.T) {
	synctest.Test(t, func(t *testing.T) {
		requests, sent := startRampLoop(t, 2*time.Second)

		requests <- &FileStreamRequest{EventsLines: []string{"{}"}}
		sent()
		requests <- &FileStreamRequest{EventsLines: []string{"{}"}}

		// Halfway through the pending batch's 15-second wait, the first
		// history leaves it half of the new 2-second interval.
		time.Sleep(7500 * time.Millisecond)
		requests <- &FileStreamRequest{HistoryLines: []string{"{}"}}
		assert.Equal(t, 8500*time.Millisecond, sent())
		close(requests)
	})
}

func TestCollectLoop_RampStartsWhileTransmitting(t *testing.T) {
	synctest.Test(t, func(t *testing.T) {
		requests, sent := startRampLoop(t, 2*time.Second)

		// The first history arrives while the loop is waiting for the
		// uploader, so it is merged into the batch already being sent.
		requests <- &FileStreamRequest{EventsLines: []string{"{}"}}
		time.Sleep(7500 * time.Millisecond)
		requests <- &FileStreamRequest{HistoryLines: []string{"{}"}}
		sent()

		// The ramp started anyway, so the next batch waits the 1 second
		// left of the 2-second interval rather than 15 seconds.
		requests <- &FileStreamRequest{EventsLines: []string{"{}"}}
		assert.Equal(t, 8500*time.Millisecond, sent())
		close(requests)
	})
}

func TestCollectLoop_NoRampIfInitialIntervalIsNotShorter(t *testing.T) {
	synctest.Test(t, func(t *testing.T) {
		requests, sent := startRampLoop(t, 30*time.Second)

		requests <- &FileStreamRequest{HistoryLines: []string{"{}"}}
		sent()
		requests <- &FileStreamRequest{HistoryLines: []string{"{}"}}
		assert.Equal(t, 15*time.Second, sent())
		close(requests)
	})
}

func TestCollectLoop_BlocksOnceAtMaxSize(t *testing.T) {
	requests := make(chan *FileStreamRequest)
	loop := CollectLoop{
		Logger:  observability.NewNoOpLogger(),
		Printer: observability.NewPrinter(0),
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
