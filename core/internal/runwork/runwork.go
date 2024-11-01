// Package runwork manages all work that's part of a run.
//
// This defines a Work type which wraps the Record proto,
// and RunWork which is like a Work channel that can be closed
// more than once and that doesn't panic if more Work is added
// after close.
package runwork

import (
	"context"
	"errors"
	"sync"
	"time"

	"github.com/wandb/wandb/core/internal/observability"
)

var errRecordAfterClose = errors.New("runwork: ignoring record after close")

// ExtraWork allows injecting tasks into the Handler->Sender pipeline.
type ExtraWork interface {
	// AddWork adds a task for the run.
	//
	// This may only be called before the end of the run---see the comment
	// on BeforeEndCtx. If called after the end of the run, the work is
	// ignored and an error is logged and captured.
	AddWork(work Work)

	// AddWorkOrCancel is like AddWork but exits early if the 'done'
	// channel is closed.
	AddWorkOrCancel(done <-chan struct{}, work Work)

	// BeforeEndCtx is a context that's cancelled when no additional work
	// may be performed for the run.
	//
	// All components should provide a "Finish" method that blocks until
	// all work completes, and that method should be invoked at the
	// appropriate time during run shutdown (that is, in the Sender "defer"
	// state machine).
	//
	// As a safety mechanism, this should be the base context for all network
	// operations to ensure they get cancelled if the component's Finish()
	// is not invoked. The resulting cancellation error should be captured.
	BeforeEndCtx() context.Context
}

// RunWork is a channel for all tasks in a run.
type RunWork interface {
	ExtraWork

	// Chan returns the channel of work for the run.
	Chan() <-chan Work

	// SetDone indicates that the run is done, allowing the channel
	// to become closed.
	SetDone()

	// Close cancels any ongoing work and closes the output channel.
	//
	// This blocks until SetDone() is called.
	//
	// It is safe to call concurrently or multiple times.
	Close()
}

type runWork struct {
	addWorkCount int        // num. goroutines in AddWork()
	addWorkCV    *sync.Cond // signalled when addWorkCount==0

	closedMu sync.Mutex    // locked for closing `closed`
	closed   chan struct{} // closed on Close()

	doneMu sync.Mutex    // locked for closing `done`
	done   chan struct{} // closed on SetDone()

	internalWork chan Work
	endCtx       context.Context
	endCtxCancel func()

	logger *observability.CoreLogger
}

func New(bufferSize int, logger *observability.CoreLogger) RunWork {
	endCtx, endCtxCancel := context.WithCancel(context.Background())

	return &runWork{
		addWorkCV:    sync.NewCond(&sync.Mutex{}),
		closed:       make(chan struct{}),
		done:         make(chan struct{}),
		internalWork: make(chan Work, bufferSize),
		endCtx:       endCtx,
		endCtxCancel: endCtxCancel,
		logger:       logger,
	}
}

func (rw *runWork) incAddWork() {
	rw.addWorkCV.L.Lock()
	defer rw.addWorkCV.L.Unlock()

	rw.addWorkCount++
}

func (rw *runWork) decAddWork() {
	rw.addWorkCV.L.Lock()
	defer rw.addWorkCV.L.Unlock()

	rw.addWorkCount--
	if rw.addWorkCount == 0 {
		rw.addWorkCV.Broadcast()
	}
}

func (rw *runWork) AddWork(work Work) {
	rw.AddWorkOrCancel(nil, work)
}

func (rw *runWork) AddWorkOrCancel(
	cancel <-chan struct{},
	work Work,
) {
	rw.incAddWork()
	defer rw.decAddWork()

	// AddWork.A

	select {
	case <-cancel:
		return

	case <-rw.closed:
		// Here, internalWork is closed or about to be closed,
		// so we should drop the record.
		rw.logger.Warn(errRecordAfterClose.Error(), "work", work)
		return

	default:
	}

	// Here, AddWork.A happened before Close.A.
	//
	// If we're racing with Close(), then it will block on line Close.B
	// until we exit and decrement addWorkCount---so internalWork
	// is guaranteed to not be closed until this method returns.

	start := time.Now()
	for i := 0; ; i++ {
		select {
		// Detect deadlocks and hangs that prevent internalWork
		// from flushing.
		case <-time.After(10 * time.Minute):
			// Stop warning after the first hour to minimize spam.
			if i < 6 {
				rw.logger.CaptureWarn(
					"runwork: taking a long time",
					"seconds", time.Since(start).Seconds(),
					"work", work.DebugInfo(),
				)
			}

		case <-rw.closed:
			// Here, Close() must have been called, so we should drop the record.
			rw.logger.CaptureError(errRecordAfterClose, "work", work)
			return

		case <-cancel:
			return

		case rw.internalWork <- work:
			if i > 0 {
				rw.logger.CaptureInfo(
					"runwork: succeeded after taking longer than expected",
					"seconds", time.Since(start).Seconds(),
					"work", work.DebugInfo(),
				)
			}

			return
		}
	}
}

func (rw *runWork) BeforeEndCtx() context.Context {
	return rw.endCtx
}

func (rw *runWork) Chan() <-chan Work {
	return rw.internalWork
}

func (rw *runWork) SetDone() {
	rw.doneMu.Lock()
	defer rw.doneMu.Unlock()

	select {
	case <-rw.done:
		// No-op, already closed.
	default:
		close(rw.done)
	}
}

func (rw *runWork) Close() {
	<-rw.done

	rw.closedMu.Lock()

	select {
	case <-rw.closed:
		rw.closedMu.Unlock()

	default:
		rw.endCtxCancel()

		close(rw.closed) // Close.A
		rw.closedMu.Unlock()

		rw.addWorkCV.L.Lock()
		for rw.addWorkCount > 0 {
			rw.addWorkCV.Wait() // Close.B
		}
		close(rw.internalWork)
		rw.addWorkCV.L.Unlock()
	}
}
