// Package runworktest provides testing utilities for runwork.
package runworktest

import (
	"context"
	"slices"
	"sync"

	"github.com/wandb/wandb/core/internal/observability"
	"github.com/wandb/wandb/core/internal/runwork"

	spb "github.com/wandb/wandb/core/pkg/service_go_proto"
)

// FakeRunWork is a fake of runwork.RunWork.
type FakeRunWork struct {
	rw runwork.RunWork

	wg         sync.WaitGroup
	mu         sync.Mutex
	allWork    []runwork.Work
	allRecords []*spb.Record
	responses  []*spb.ServerResponse
}

var _ runwork.RunWork = &FakeRunWork{}

func New() *FakeRunWork {
	fake := &FakeRunWork{rw: runwork.New(0, observability.NewNoOpLogger())}

	go func() {
		for work := range fake.rw.Chan() {
			fake.acceptWork(work)
		}
	}()

	return fake
}

// acceptWork processes a single work item.
func (w *FakeRunWork) acceptWork(work runwork.Work) {
	defer w.wg.Done()

	w.mu.Lock()
	defer w.mu.Unlock()

	w.allWork = append(w.allWork, work)
	if rec, ok := work.WorkImpl.(runwork.WorkRecord); ok {
		w.allRecords = append(w.allRecords, rec.Record)
	}

	if work.Request == nil || len(w.responses) == 0 {
		go work.Request.WillNotRespond()
	} else {
		response := w.responses[0]
		w.responses = slices.Clone(w.responses[1:])
		go work.Request.Respond(response)
	}
}

// QueueResponse adds a response to the response queue.
//
// Once the response is at the front of the queue, it is returned for the next
// non-nil request. If the response queue is empty, the request receives an
// error response.
func (w *FakeRunWork) QueueResponse(response *spb.ServerResponse) {
	w.mu.Lock()
	defer w.mu.Unlock()
	w.responses = append(w.responses, response)
}

// AllWork returns all work added via AddWork.
func (w *FakeRunWork) AllWork() []runwork.Work {
	w.wg.Wait()

	w.mu.Lock()
	defer w.mu.Unlock()
	return w.allWork
}

// AllWorkImpls returns all work impl objects added via AddWork.
//
// This is useful in conjunction with using mock runwork.WorkImpl objects.
func (w *FakeRunWork) AllWorkImpls() []runwork.WorkImpl {
	allWork := w.AllWork()

	allWorkImpls := make([]runwork.WorkImpl, len(allWork))
	for i, work := range allWork {
		allWorkImpls[i] = work.WorkImpl
	}

	return allWorkImpls
}

// AllRecords returns all records added via AddWork.
func (w *FakeRunWork) AllRecords() []*spb.Record {
	w.wg.Wait()

	w.mu.Lock()
	defer w.mu.Unlock()
	return w.allRecords
}

func (w *FakeRunWork) AddWork(work runwork.Work) {
	w.wg.Add(1)
	w.rw.AddWork(work)
}

func (w *FakeRunWork) AddWorkOrCancel(
	done <-chan struct{},
	work runwork.Work,
) {
	w.wg.Add(1)
	w.rw.AddWorkOrCancel(done, work)
}

func (w *FakeRunWork) BeforeEndCtx() context.Context {
	return w.rw.BeforeEndCtx()
}

func (w *FakeRunWork) Chan() <-chan runwork.Work {
	panic("FakeRunWork.Chan() is not implemented")
}

func (w *FakeRunWork) Abort() {
	w.rw.Abort()
}

func (w *FakeRunWork) Close() {
	w.rw.Close()
}
