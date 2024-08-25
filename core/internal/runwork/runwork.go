// Package runwork manages all work that's part of a run.
//
// This defines a channel-like object for Record protos that can be
// safely closed.
package runwork

import (
	"context"
	"errors"
	"sync"

	"github.com/wandb/wandb/core/pkg/observability"
	spb "github.com/wandb/wandb/core/pkg/service_go_proto"
)

var errRecordAfterClose = errors.New("runwork: ignoring record after close")

// ExtraWork allows injecting records into the Handler->Sender pipeline.
type ExtraWork interface {
	// AddRecord emits a record to process for the run.
	//
	// This may only be called before the end of the run---see the comment
	// on BeforeEndCtx. If called after the end of the run, the record is
	// ignored and an error is logged and captured.
	AddRecord(record *spb.Record)

	// AddRecordOrCancel is like AddRecord but exits early if the 'done'
	// channel is closed.
	AddRecordOrCancel(done <-chan struct{}, record *spb.Record)

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

// RunWork is a channel for all records to process in a run.
type RunWork interface {
	ExtraWork

	// Chan returns the channel of records added via AddRecord.
	Chan() <-chan *spb.Record

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
	addRecordCount int        // num. goroutines in AddRecord()
	addRecordCV    *sync.Cond // signalled when addRecordCount==0

	closedMu sync.Mutex    // locked for closing `closed`
	closed   chan struct{} // closed on Close()

	doneMu sync.Mutex    // locked for closing `done`
	done   chan struct{} // closed on SetDone()

	internalRecords chan *spb.Record
	endCtx          context.Context
	endCtxCancel    func()

	logger *observability.CoreLogger
}

func New(bufferSize int, logger *observability.CoreLogger) RunWork {
	endCtx, endCtxCancel := context.WithCancel(context.Background())

	return &runWork{
		addRecordCV:     sync.NewCond(&sync.Mutex{}),
		closed:          make(chan struct{}),
		done:            make(chan struct{}),
		internalRecords: make(chan *spb.Record, bufferSize),
		endCtx:          endCtx,
		endCtxCancel:    endCtxCancel,
		logger:          logger,
	}
}

func (rw *runWork) incAddRecord() {
	rw.addRecordCV.L.Lock()
	defer rw.addRecordCV.L.Unlock()

	rw.addRecordCount++
}

func (rw *runWork) decAddRecord() {
	rw.addRecordCV.L.Lock()
	defer rw.addRecordCV.L.Unlock()

	rw.addRecordCount--
	if rw.addRecordCount == 0 {
		rw.addRecordCV.Broadcast()
	}
}

func (rw *runWork) AddRecord(record *spb.Record) {
	rw.AddRecordOrCancel(nil, record)
}

func (rw *runWork) AddRecordOrCancel(
	cancel <-chan struct{},
	record *spb.Record,
) {
	rw.incAddRecord()
	defer rw.decAddRecord()

	// AddRecord.A

	select {
	case <-cancel:
		return

	case <-rw.closed:
		// Here, internalRecords is closed or about to be closed,
		// so we should drop the record.
		rw.logger.CaptureError(errRecordAfterClose, "record", record)
		return

	default:
	}

	// Here, AddRecord.A happened before Close.A.
	//
	// If we're racing with Close(), then it will block on line Close.B
	// until we exit and decrement addRecordCount---so internalRecords
	// is guaranteed to not be closed until this method returns.

	select {
	case <-rw.closed:
		// Here, Close() must have been called, so we should drop the record.
		rw.logger.CaptureError(errRecordAfterClose, "record", record)

	case <-cancel:
	case rw.internalRecords <- record:
	}
}

func (rw *runWork) BeforeEndCtx() context.Context {
	return rw.endCtx
}

func (rw *runWork) Chan() <-chan *spb.Record {
	return rw.internalRecords
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

		rw.addRecordCV.L.Lock()
		for rw.addRecordCount > 0 {
			rw.addRecordCV.Wait() // Close.B
		}
		close(rw.internalRecords)
		rw.addRecordCV.L.Unlock()
	}
}
