// Package runworktest provides testing utilities for runwork.
package runworktest

import (
	"context"
	"sync"

	"github.com/wandb/wandb/core/internal/runwork"
	"github.com/wandb/wandb/core/pkg/observability"
	"github.com/wandb/wandb/core/pkg/service"
)

// FakeRunWork is a fake of runwork.RunWork.
type FakeRunWork struct {
	rw runwork.RunWork

	mu         sync.Mutex
	allRecords []*service.Record
}

var _ runwork.RunWork = &FakeRunWork{}

func New() *FakeRunWork {
	fake := &FakeRunWork{rw: runwork.New(0, observability.NewNoOpLogger())}

	go func() {
		for x := range fake.rw.Chan() {
			fake.mu.Lock()
			fake.allRecords = append(fake.allRecords, x)
			fake.mu.Unlock()
		}
	}()

	return fake
}

// AllRecords returns all records added via AddRecord.
func (w *FakeRunWork) AllRecords() []*service.Record {
	w.mu.Lock()
	defer w.mu.Unlock()
	return w.allRecords
}

func (w *FakeRunWork) AddRecord(record *service.Record) {
	w.rw.AddRecord(record)
}

func (w *FakeRunWork) AddRecordOrCancel(
	done <-chan struct{},
	record *service.Record,
) {
	w.rw.AddRecordOrCancel(done, record)
}

func (w *FakeRunWork) BeforeEndCtx() context.Context {
	return w.rw.BeforeEndCtx()
}

func (w *FakeRunWork) Chan() <-chan *service.Record {
	panic("FakeRunWork.Chan() is not implemented")
}

func (w *FakeRunWork) SetDone() {
	w.rw.SetDone()
}

func (w *FakeRunWork) Close() {
	w.rw.Close()
}
