// Package runworktest provides testing utilities for runwork.
package runworktest

import (
	"context"
	"sync"

	"github.com/wandb/wandb/core/internal/runwork"
	"github.com/wandb/wandb/core/pkg/observability"

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
			fake.mu.Lock()
			fake.allRecords = append(fake.allRecords, x)
			fake.mu.Unlock()
			fake.wg.Done()
		}
	}()

	return fake
}

// AllRecords returns all records added via AddRecord.
func (w *FakeRunWork) AllRecords() []*spb.Record {
	w.wg.Wait()

	w.mu.Lock()
	defer w.mu.Unlock()
	return w.allRecords
}

func (w *FakeRunWork) AddRecord(record *spb.Record) {
	w.wg.Add(1)
	w.rw.AddRecord(record)
}

func (w *FakeRunWork) AddRecordOrCancel(
	done <-chan struct{},
	record *spb.Record,
) {
	w.wg.Add(1)
	w.rw.AddRecordOrCancel(done, record)
}

func (w *FakeRunWork) BeforeEndCtx() context.Context {
	return w.rw.BeforeEndCtx()
}

func (w *FakeRunWork) Chan() <-chan *spb.Record {
	panic("FakeRunWork.Chan() is not implemented")
}

func (w *FakeRunWork) SetDone() {
	w.rw.SetDone()
}

func (w *FakeRunWork) Close() {
	w.rw.Close()
}
