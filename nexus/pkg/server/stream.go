package server

import (
	"context"
	"sync"

	"github.com/wandb/wandb/nexus/pkg/analytics"
	"github.com/wandb/wandb/nexus/pkg/service"
)

// Stream is a collection of components that work together to handle incoming
// data for a W&B run, store it locally, and send it to a W&B server.
// Stream.handler receives incoming data from the client and dispatches it to
// Stream.writer, which writes it to a local file. Stream.writer then sends the
// data to Stream.sender, which sends it to the W&B server. Stream.dispatcher
// handles dispatching responses to the appropriate client responders.
type Stream struct {
	// ctx is the context for the stream
	ctx context.Context

	// wg is the WaitGroup for the stream
	wg sync.WaitGroup

	// handler is the handler for the stream
	handler *Handler

	// dispatcher is the dispatcher for the stream
	dispatcher *Dispatcher

	// writer is the writer for the stream
	writer *Writer

	// sender is the sender for the stream
	sender *Sender

	// settings is the settings for the stream
	settings *service.Settings

	// logger is the logger for the stream
	logger *analytics.NexusLogger
}

// NewStream creates a new stream with the given settings and responders.
func NewStream(ctx context.Context, settings *service.Settings, streamId string, responders ...ResponderEntry) *Stream {
	logFile := settings.GetLogInternal().GetValue()
	logger := analytics.NewNexusLogger(SetupStreamLogger(logFile, streamId), settings)

	dispatcher := NewDispatcher(ctx, logger)
	sender := NewSender(ctx, settings, logger)
	writer := NewWriter(ctx, settings, logger)
	handler := NewHandler(ctx, settings, logger)

	// connect the components
	writer.outChan = sender.inChan
	handler.outChan = writer.inChan
	sender.outChan = handler.inChan

	// connect the dispatcher to the handler and sender
	handler.dispatcherChan = dispatcher.inChan
	sender.dispatcherChan = dispatcher.inChan

	stream := &Stream{
		ctx:        ctx,
		wg:         sync.WaitGroup{},
		dispatcher: dispatcher,
		handler:    handler,
		sender:     sender,
		writer:     writer,
		settings:   settings,
		logger:     logger,
	}
	stream.wg.Add(1)
	go stream.Start()
	return stream
}

// AddResponders adds the given responders to the stream's dispatcher.
func (s *Stream) AddResponders(entries ...ResponderEntry) {
	for _, entry := range entries {
		s.dispatcher.AddResponder(entry)
	}
}

// Start starts the stream's handler, writer, sender, and dispatcher.
// We use Stream's wait group to ensure that all of these components are cleanly
// finalized and closed when the stream is closed in Stream.Close().
func (s *Stream) Start() {
	defer s.wg.Done()
	s.logger.Info("created new stream", "id", s.settings.RunId)

	// handle the client requests
	s.wg.Add(1)
	go func() {
		s.handler.do()
		s.wg.Done()
	}()

	// write the data to a transaction log
	s.wg.Add(1)
	go func() {
		s.writer.do()
		s.wg.Done()
	}()

	// send the data to the server
	s.wg.Add(1)
	go func() {
		s.sender.do()
		s.wg.Done()
	}()

	// dispatch responses to the client
	s.wg.Add(1)
	go func() {
		s.dispatcher.do()
		s.wg.Done()
	}()
}

// HandleRecord handles the given record by sending it to the stream's handler.
func (s *Stream) HandleRecord(rec *service.Record) {
	s.logger.Debug("handling record", "record", rec)
	s.handler.inChan <- rec
}

func (s *Stream) GetRun() *service.RunRecord {
	return s.handler.GetRun()
}

// Close closes the stream's handler, writer, sender, and dispatcher.
// This can be triggered by the client (force=False) or by the server (force=True).
// We need the ExitRecord to initiate the shutdown procedure (which we
// either get from the client, or generate ourselves if the server is shutting us down).
// This will trigger the defer state machines (SM) in the stream's components:
//   - when the sender's SM gets to the final state, it will Close the handler
//   - this will trigger the handler to Close the writer
//   - this will trigger the writer to Close the sender
//   - this will trigger the sender to Close the dispatcher
//
// This will finish the Stream's wait group, which will allow the stream to be
// garbage collected.
func (s *Stream) Close(force bool) {
	// send exit record to handler
	if force {
		record := &service.Record{
			RecordType: &service.Record_Exit{Exit: &service.RunExitRecord{}},
			Control:    &service.Control{AlwaysSend: true},
		}
		s.HandleRecord(record)
	}
	s.wg.Wait()
	if force {
		s.PrintFooter()
	}
	s.logger.Info("closed stream", "id", s.settings.RunId)
}

func (s *Stream) PrintFooter() {
	run := s.GetRun()
	PrintHeadFoot(run, s.settings)
}
