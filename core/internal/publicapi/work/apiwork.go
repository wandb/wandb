package work

import (
	"context"
	"errors"
	"sync"

	"github.com/wandb/wandb/core/internal/observability"
	spb "github.com/wandb/wandb/core/pkg/service_go_proto"
)

var errWorkAfterClose = errors.New("apiwork: ignoring work after close")

type ApiWork interface {
	Process(outChan chan<- *spb.Result)
}

// ApiWorkManager manages the work for an API stream.
type ApiWorkManager interface {
	// Add work adds api work to the work queue.
	AddWork(work ApiWork)

	// Chan returns the channel of api work.
	Chan() <-chan ApiWork

	// SetDone indicates that the api work manager is done.
	SetDone()

	// Close closes the api worker.
	Close()

	// EndCtx returns the context which is cancelled when Close is called.
	EndCtx() context.Context
}

type apiWorkStruct struct {
	addWorkCount int
	addWorkCV    *sync.Cond

	closedMu sync.Mutex
	closed   chan struct{}

	doneMu sync.Mutex
	done   chan struct{}

	internalWork chan ApiWork
	endCtx       context.Context
	endCtxCancel func()

	logger *observability.CoreLogger
}

func NewWorkManager(
	bufferSize int,
	logger *observability.CoreLogger,
) ApiWorkManager {
	endCtx, endCtxCancel := context.WithCancel(context.Background())

	return &apiWorkStruct{
		addWorkCV:    sync.NewCond(&sync.Mutex{}),
		closed:       make(chan struct{}),
		done:         make(chan struct{}),
		endCtx:       endCtx,
		endCtxCancel: endCtxCancel,
		internalWork: make(chan ApiWork, bufferSize),
		logger:       logger,
	}
}

func (aw *apiWorkStruct) incAddWork() {
	aw.addWorkCV.L.Lock()
	defer aw.addWorkCV.L.Unlock()

	aw.addWorkCount++
}

func (aw *apiWorkStruct) decAddWork() {
	aw.addWorkCV.L.Lock()
	defer aw.addWorkCV.L.Unlock()

	aw.addWorkCount--
	if aw.addWorkCount == 0 {
		aw.addWorkCV.Broadcast()
	}
}

// AddWork implements ApiWorker.AddWork
func (aw *apiWorkStruct) AddWork(work ApiWork) {
	aw.incAddWork()
	defer aw.decAddWork()

	select {
	case <-aw.closed:
		aw.logger.Warn(errWorkAfterClose.Error(), "work", work)
		return
	default:
	}

	aw.internalWork <- work
}

func (aw *apiWorkStruct) Chan() <-chan ApiWork {
	return aw.internalWork
}

func (aw *apiWorkStruct) Close() {
	<-aw.done

	aw.closedMu.Lock()
	select {
	case <-aw.closed:
		aw.closedMu.Unlock()
	default:
		aw.endCtxCancel()
		close(aw.closed)
		aw.closedMu.Unlock()

		aw.addWorkCV.L.Lock()

		for aw.addWorkCount > 0 {
			aw.addWorkCV.Wait()
		}
		close(aw.internalWork)
		aw.addWorkCV.L.Unlock()
	}
}

func (aw *apiWorkStruct) SetDone() {
	aw.doneMu.Lock()
	defer aw.doneMu.Unlock()

	select {
	case <-aw.done:
		// No-op, already closed.
	default:
		close(aw.done)
	}
}

func (aw *apiWorkStruct) EndCtx() context.Context {
	return aw.endCtx
}
