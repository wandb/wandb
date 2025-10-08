package publicapi

import (
	"testing"

	"github.com/stretchr/testify/assert"
	"github.com/wandb/wandb/core/internal/observabilitytest"
	"github.com/wandb/wandb/core/internal/publicapi/work"
	"github.com/wandb/wandb/core/internal/settings"
	spb "github.com/wandb/wandb/core/pkg/service_go_proto"
)

type testWork struct{}

func (w *testWork) Process(outChan chan<- *spb.Result) {
	outChan <- &spb.Result{
		ResultType: &spb.Result_Response{Response: &spb.Response{}},
	}
}

func TestHandleRecord(t *testing.T) {
	recordParser := &work.RecordParser{
		Logger:   observabilitytest.NewTestLogger(t),
		Settings: settings.New(),
	}
	handler := NewApiWorkHandler(observabilitytest.NewTestLogger(t), recordParser)
	done := make(chan struct{})
	var result *spb.Result
	go func() {
		result = <-handler.ResponseChan()
		close(done)
	}()

	handler.HandleRecord(&spb.Record{
		RecordType: &spb.Record_Request{
			Request: &spb.Request{},
		},
	})

	<-done
	assert.Equal(t, &spb.Response{}, result.GetResponse())
}

func TestCloseAfterClose(t *testing.T) {
	handler := NewApiWorkHandler(observabilitytest.NewTestLogger(t), &work.RecordParser{})
	handler.Close()
	handler.Close()
}

func TestDoProcessesWork(t *testing.T) {
	handler := NewApiWorkHandler(observabilitytest.NewTestLogger(t), &work.RecordParser{})
	outChan := handler.ResponseChan()
	done := make(chan struct{})
	var result *spb.Result
	go func() {
		result = <-outChan
		close(done)
	}()
	workChan := make(chan work.ApiWork, 1)

	go handler.Do(workChan)
	workChan <- &testWork{}

	<-done
	assert.Equal(t, &spb.Response{}, result.GetResponse())
}
