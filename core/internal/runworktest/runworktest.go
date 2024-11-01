// Package runworktest provides testing utilities for runwork.
package runworktest

import (
	"context"
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
	allRecords []*spb.Record
}

var _ runwork.RunWork = &FakeRunWork{}

func New() *FakeRunWork {
	fake := &FakeRunWork{rw: runwork.New(0, observability.NewNoOpLogger())}

	go func() {
		for x := range fake.rw.Chan() {
			if rec, ok := x.(runwork.WorkRecord); ok {
				fake.mu.Lock()
				fake.allRecords = append(fake.allRecords, rec.Record)
				fake.mu.Unlock()
			}
			fake.wg.Done()
		}
	}()

	return fake
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

func (w *FakeRunWork) SetDone() {
	w.rw.SetDone()
}

func (w *FakeRunWork) Close() {
	w.rw.Close()
}
