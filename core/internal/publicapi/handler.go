package publicapi

import (
	"sync"

	"github.com/wandb/wandb/core/internal/observability"
	"github.com/wandb/wandb/core/internal/publicapi/work"
	spb "github.com/wandb/wandb/core/pkg/service_go_proto"
)

const BufferSize = 32

// ApiWorkHandler handles processing work for an API stream.
type ApiWorkHandler struct {
	recordParser   *work.RecordParser
	apiWorkManager work.ApiWorkManager
	logger         *observability.CoreLogger
	outChan        chan *spb.Result
	wg             sync.WaitGroup
	started        chan struct{}
}

func NewApiWorkHandler(
	logger *observability.CoreLogger,
	recordParser *work.RecordParser,
) *ApiWorkHandler {
	apiWorkManager := work.NewWorkManager(BufferSize, logger)
	return &ApiWorkHandler{
		logger:         logger,
		outChan:        make(chan *spb.Result),
		wg:             sync.WaitGroup{},
		apiWorkManager: apiWorkManager,
		recordParser:   recordParser,
		started:        make(chan struct{}),
	}
}

func (h *ApiWorkHandler) WorkChan() <-chan work.ApiWork {
	return h.apiWorkManager.Chan()
}

func (h *ApiWorkHandler) ResponseChan() <-chan *spb.Result {
	return h.outChan
}

func (h *ApiWorkHandler) HandleRecord(record *spb.Record) {
	work := h.recordParser.Parse(record)
	if work == nil {
		// TODO: handle invalid record
		h.respond(record, &spb.Response{})
		return
	}
	h.apiWorkManager.AddWork(work)
}

// Do processes all work on the input channel.
func (h *ApiWorkHandler) Do(allWork <-chan work.ApiWork) {
	defer h.logger.Reraise()
	h.logger.Info("api handler: started")
	for work := range allWork {
		h.logger.Debug("api handler: got work", "work", work)
		work.Process(h.outChan)
	}
}

// Close closes the api work to prevent further work from being added.
//
// It is safe to call concurrently or multiple times.
func (h *ApiWorkHandler) Close() {
	h.apiWorkManager.SetDone()
	h.apiWorkManager.Close()
}

func (h *ApiWorkHandler) respond(record *spb.Record, response *spb.Response) {
	result := &spb.Result{
		ResultType: &spb.Result_Response{Response: response},
		Control:    record.Control,
		Uuid:       record.Uuid,
	}
	h.outChan <- result
}
