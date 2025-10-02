package work

import (
	"sync"
	"testing"
	"time"

	"github.com/stretchr/testify/assert"
	"github.com/wandb/wandb/core/internal/observabilitytest"
	spb "github.com/wandb/wandb/core/pkg/service_go_proto"
)

type NoopWork struct {
	Record *spb.Record
}

var _ ApiWork = &NoopWork{}

func (w *NoopWork) Process(outChan chan<- *spb.Result) {
	outChan <- &spb.Result{
		ResultType: &spb.Result_Response{Response: &spb.Response{}},
	}
}

func TestAddWorkConcurrent(t *testing.T) {
	count := 0
	aw := NewWorkManager(0, observabilitytest.NewTestLogger(t))
	wgConsumer := &sync.WaitGroup{}
	wgConsumer.Go(func() {
		for range aw.Chan() {
			count++
		}
	})

	wgProducer := &sync.WaitGroup{}
	for range 5 {
		wgProducer.Go(func() {
			for range 100 {
				aw.AddWork(&NoopWork{})
			}
		})
	}
	wgProducer.Wait()
	aw.SetDone()
	aw.Close()
	wgConsumer.Wait()

	assert.Equal(t, 5*100, count)
}

func TestAddWorkAfterClose(t *testing.T) {
	logger, logs := observabilitytest.NewRecordingTestLogger(t)
	aw := NewWorkManager(0, logger)

	aw.SetDone()
	aw.Close()
	aw.AddWork(&NoopWork{})

	assert.Contains(t, logs.String(), errWorkAfterClose.Error())
}

func TestCloseAfterClose(t *testing.T) {
	aw := NewWorkManager(0, observabilitytest.NewTestLogger(t))

	aw.SetDone()
	aw.SetDone()
	aw.Close()
	aw.Close()
}

func TestCloseCancelsContext(t *testing.T) {
	aw := NewWorkManager(0, observabilitytest.NewTestLogger(t))

	aw.SetDone()
	aw.Close()
	<-aw.EndCtx().Done()

	assert.Error(t, aw.EndCtx().Err())
}

func TestCloseBlocksUntilDone(t *testing.T) {
	aw := NewWorkManager(0, observabilitytest.NewTestLogger(t))
	wg := &sync.WaitGroup{}
	count := 0

	wg.Go(func() {
		for range aw.Chan() {
			count++
		}
	})

	go aw.Close()
	for range 10 {
		<-time.After(time.Millisecond)
		aw.AddWork(&NoopWork{})
	}
	aw.SetDone()
	wg.Wait()

	assert.Equal(t, 10, count)
}
