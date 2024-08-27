package runwork_test

import (
	"bytes"
	"log/slog"
	"sync"
	"testing"
	"time"

	"github.com/stretchr/testify/assert"
	"github.com/wandb/wandb/core/internal/runwork"
	"github.com/wandb/wandb/core/pkg/observability"
	spb "github.com/wandb/wandb/core/pkg/service_go_proto"
)

func TestAddRecordConcurrent(t *testing.T) {
	count := 0
	rw := runwork.New(0, observability.NewNoOpLogger())
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
				rw.AddRecord(&spb.Record{})
			}
		}()
	}
	wgProducer.Wait()
	rw.SetDone()
	rw.Close()
	wgConsumer.Wait()

	assert.Equal(t, 5*100, count)
}

func TestAddRecordAfterClose(t *testing.T) {
	logs := bytes.Buffer{}
	logger := slog.New(slog.NewTextHandler(&logs, &slog.HandlerOptions{}))
	rw := runwork.New(0, observability.NewCoreLogger(logger))

	rw.SetDone()
	rw.Close()
	rw.AddRecord(&spb.Record{})

	assert.Contains(t, logs.String(), "runwork: ignoring record after close")
}

func TestCloseDuringAddRecord(t *testing.T) {
	logs := bytes.Buffer{}
	logger := slog.New(slog.NewTextHandler(&logs, &slog.HandlerOptions{}))
	rw := runwork.New(0, observability.NewCoreLogger(logger))

	go func() {
		// Increase odds that Close() happens while AddRecord() is
		// blocked on a channel write.
		<-time.After(5 * time.Millisecond)
		rw.SetDone()
		rw.Close()
	}()
	rw.AddRecord(&spb.Record{})
	<-rw.Chan()

	assert.Contains(t, logs.String(), "runwork: ignoring record after close")
}

func TestCloseAfterClose(t *testing.T) {
	rw := runwork.New(0, observability.NewNoOpLogger())

	rw.SetDone()
	rw.SetDone()
	rw.Close()
	rw.Close()

	// Should reach here with no issues.
}

func TestRaceAddRecordClose(t *testing.T) {
	for range 50 {
		rw := runwork.New(0, observability.NewNoOpLogger())

		go func() {
			rw.SetDone()
			rw.Close()
		}()
		go rw.AddRecord(&spb.Record{})
		<-rw.Chan()
	}
}

func TestCloseCancelsContext(t *testing.T) {
	rw := runwork.New(0, observability.NewNoOpLogger())

	go func() {
		rw.SetDone()
		rw.Close()
	}()
	<-rw.BeforeEndCtx().Done()

	assert.Error(t, rw.BeforeEndCtx().Err())
}

func TestCloseBlocksUntilDone(t *testing.T) {
	rw := runwork.New(0, observability.NewNoOpLogger())
	wg := &sync.WaitGroup{}
	count := 0

	wg.Add(1)
	go func() {
		defer wg.Done()
		for range rw.Chan() {
			count++
		}
	}()

	// All AddRecord() calls should go despite racing with Close()
	// because SetDone() is only called at the end.
	go rw.Close()
	for range 10 {
		<-time.After(time.Millisecond)
		rw.AddRecord(&spb.Record{})
	}
	rw.SetDone()
	wg.Wait()

	assert.Equal(t, 10, count)
}
