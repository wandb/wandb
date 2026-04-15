package runwork_test

import (
	"bytes"
	"context"
	"log/slog"
	"sync"
	"testing"
	"testing/synctest"
	"time"

	"github.com/stretchr/testify/assert"

	"github.com/wandb/wandb/core/internal/observability"
	"github.com/wandb/wandb/core/internal/observabilitytest"
	"github.com/wandb/wandb/core/internal/runwork"
	spb "github.com/wandb/wandb/core/pkg/service_go_proto"
)

// newTestRequest returns a fake Request for testing for when the response
// can be ignored.
func newTestRequest(t *testing.T) *runwork.Request {
	t.Helper()

	ctx, cancelCtx := context.WithCancel(t.Context())
	return runwork.NewRequest(
		"test-request",
		ctx,
		cancelCtx,
		make(chan<- *spb.ServerResponse, 1),
	)
}

// assertCancelled fails if the context is not cancelled.
func assertCancelled(t *testing.T, ctx context.Context) {
	t.Helper()

	select {
	case <-ctx.Done():
	default:
		t.Error("Did not cancel context.")
	}
}

func TestAddWorkConcurrent(t *testing.T) {
	count := 0
	rw := runwork.New(0, observabilitytest.NewTestLogger(t))
	wgConsumer := &sync.WaitGroup{}
	wgConsumer.Add(1)
	go func() {
		defer wgConsumer.Done()
		for range rw.Chan() {
			count++
		}
	}()

	wgProducer := &sync.WaitGroup{}
	for range 5 {
		wgProducer.Add(1)
		go func() {
			defer wgProducer.Done()
			for range 100 {
				rw.AddWork(runwork.NoRequest(
					runwork.WorkFromRecord(&spb.Record{}),
				))
			}
		}()
	}
	wgProducer.Wait()
	rw.Close()
	wgConsumer.Wait()

	assert.Equal(t, 5*100, count)
}

func TestAddWorkAfterClose(t *testing.T) {
	logs := bytes.Buffer{}
	logger := slog.New(slog.NewTextHandler(&logs, &slog.HandlerOptions{}))
	rw := runwork.New(0, observability.NewCoreLogger(logger, nil))
	req := newTestRequest(t)

	rw.Close()
	rw.AddWork(runwork.Work{
		WorkImpl: runwork.WorkFromRecord(&spb.Record{}),
		Request:  req,
	})

	assert.Contains(t, logs.String(), "runwork: ignoring record after close")
	assertCancelled(t, req.Context())
}

func TestCloseDuringAddWork(t *testing.T) {
	logs := bytes.Buffer{}
	logger := slog.New(slog.NewTextHandler(&logs, &slog.HandlerOptions{}))
	rw := runwork.New(0, observability.NewCoreLogger(logger, nil))
	req := newTestRequest(t)

	go func() {
		// Increase odds that Close() happens while AddWork() is
		// blocked on a channel write.
		<-time.After(5 * time.Millisecond)
		rw.Close()
	}()
	rw.AddWork(runwork.Work{
		WorkImpl: runwork.WorkFromRecord(&spb.Record{}),
		Request:  req,
	})
	<-rw.Chan()

	assert.Contains(t, logs.String(), "runwork: ignoring record after close")
	assertCancelled(t, req.Context())
}

func TestCloseAfterClose(t *testing.T) {
	rw := runwork.New(0, observabilitytest.NewTestLogger(t))

	rw.Close()
	rw.Close()

	// Should reach here with no issues.
}

func TestRaceAddWorkClose(t *testing.T) {
	synctest.Test(t, func(t *testing.T) {
		for range 50 {
			// Don't use a test logger since AddWork() can emit a warning
			// and this test doesn't wait for goroutines to exit.
			rw := runwork.New(0, observability.NewNoOpLogger())

			go rw.Close()
			go rw.AddWork(runwork.NoRequest(
				runwork.WorkFromRecord(&spb.Record{}),
			))
			<-rw.Chan() // expected not to block despite the race
		}
	})
}

func TestCloseCancelsContext(t *testing.T) {
	rw := runwork.New(0, observabilitytest.NewTestLogger(t))

	go rw.Close()
	<-rw.BeforeEndCtx().Done()

	assert.Error(t, rw.BeforeEndCtx().Err())
}

func Test_AddWorkOrCancel_CancelledBefore(t *testing.T) {
	rw := runwork.New(0, observabilitytest.NewTestLogger(t))
	req := newTestRequest(t)
	closedCh := make(chan struct{})
	close(closedCh)

	rw.AddWorkOrCancel(closedCh, runwork.Work{
		WorkImpl: runwork.WorkFromRecord(&spb.Record{}),
		Request:  req,
	})

	assertCancelled(t, req.Context())
}

func Test_AddWorkOrCancel_CancelledDuring(t *testing.T) {
	synctest.Test(t, func(t *testing.T) {
		rw := runwork.New(0, observabilitytest.NewTestLogger(t))
		req := newTestRequest(t)
		doneCh := make(chan struct{})

		go rw.AddWorkOrCancel(doneCh, runwork.Work{
			WorkImpl: runwork.WorkFromRecord(&spb.Record{}),
			Request:  req,
		})
		synctest.Wait() // wait for AddWorkOrCancel to block
		close(doneCh)
		synctest.Wait() // wait for AddWorkOrCancel to react

		assertCancelled(t, req.Context())
	})
}
