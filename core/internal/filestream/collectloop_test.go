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

func TestCollectLoop_RampsAfterFirstHistory(t *testing.T) {
	synctest.Test(t, func(t *testing.T) {
		requests := make(chan *FileStreamRequest)
		loop := CollectLoop{
			Logger:                  observability.NewNoOpLogger(),
			Printer:                 observability.NewPrinter(0),
			TransmitInterval:        15 * time.Second,
			InitialTransmitInterval: 2 * time.Second,
		}
		defer loop.Printer.Close()
		state := &FileStreamState{MaxRequestSizeBytes: 99999}
		start := time.Now()

		transmissions := loop.Start(state, requests)
		var sentAt []time.Duration
		nextRequest := func() {
			_, ok := transmissions.NextRequest(make(<-chan time.Time))
			require.True(t, ok)
			sentAt = append(sentAt, time.Since(start))
		}

		// Without history, the second batch waits the steady-state interval.
		requests <- &FileStreamRequest{EventsLines: []string{"{}"}}
		nextRequest()
		requests <- &FileStreamRequest{EventsLines: []string{"{}"}}

		// The first history starts the ramp and speeds up the pending batch.
		time.Sleep(time.Second)
		requests <- &FileStreamRequest{HistoryLines: []string{"{}"}}
		nextRequest()

		// Spacing is measured from when a batch was due, not from when
		// a slow consumer picked it up.
		requests <- &FileStreamRequest{HistoryLines: []string{"{}"}}
		time.Sleep(3 * time.Second)
		nextRequest()

		// The interval doubles until it reaches the steady-state interval.
		for range 3 {
			requests <- &FileStreamRequest{HistoryLines: []string{"{}"}}
			nextRequest()
		}
		close(requests)

		assert.Equal(t,
			[]time.Duration{
				0,
				2 * time.Second,
				5 * time.Second,
				8 * time.Second,
				16 * time.Second,
				31 * time.Second,
			},
			sentAt)
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
