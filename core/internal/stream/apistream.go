package stream

import (
	"sync"

	"github.com/wandb/wandb/core/internal/observability"
	"github.com/wandb/wandb/core/internal/publicapi"
	"github.com/wandb/wandb/core/internal/settings"
	spb "github.com/wandb/wandb/core/pkg/service_go_proto"
)

// ApiStream is a Stream that is used to send records to the server,
// which originate from the W&B SDK's public API.
type ApiStream struct {
	StreamID string

	apiHandler *publicapi.ApiWorkHandler
	dispatcher *Dispatcher
	logger     *observability.CoreLogger
	settings   *settings.Settings
	wg         sync.WaitGroup
}

// NewApiStream creates a new ApiStream.
func NewApiStream(
	streamID string,
	settings *settings.Settings,
	apiWorkHandler *publicapi.ApiWorkHandler,
	logger *observability.CoreLogger,
) *ApiStream {
	return &ApiStream{
		StreamID: streamID,

		apiHandler: apiWorkHandler,
		dispatcher: NewDispatcher(logger),
		logger:     logger,
		settings:   settings,
		wg:         sync.WaitGroup{},
	}
}

// Start implements Stream.Start.
func (s *ApiStream) Start() {
	s.logger.Debug("api stream: starting")
	s.wg.Add(1)
	go func() {
		s.apiHandler.Do(s.apiHandler.WorkChan())
		s.wg.Done()
	}()

	s.wg.Add(1)
	go func() {
		for result := range s.apiHandler.ResponseChan() {
			s.dispatcher.handleRespond(result)
		}
		s.wg.Done()
	}()
}

// HandleRecord implements Stream.HandleRecord.
func (s *ApiStream) HandleRecord(record *spb.Record) {
	s.wg.Add(1)
	go func() {
		s.apiHandler.HandleRecord(record)
		s.wg.Done()
	}()
}

// GetSettings implements Stream.GetSettings.
func (s *ApiStream) GetSettings() *settings.Settings {
	return s.settings
}

// AddResponders implements Stream.AddResponders.
func (s *ApiStream) AddResponders(entries ...ResponderEntry) {
	s.dispatcher.AddResponders(entries...)
}

// Close implements Stream.Close.
func (s *ApiStream) Close() {
	s.apiHandler.Close()
}

// FinishAndClose implements Stream.FinishAndClose.
func (s *ApiStream) FinishAndClose(exitCode int32) {
	s.Close()
}
