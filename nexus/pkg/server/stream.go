package server

import (
	"context"
	"sync"

	"github.com/wandb/wandb/nexus/internal/shared"
	"github.com/wandb/wandb/nexus/pkg/observability"
	"github.com/wandb/wandb/nexus/pkg/service"
)

const (
	internalConnectionId = "internal"
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

	// cancel is the cancel function for the stream
	cancel context.CancelFunc

	// wg is the WaitGroup for the stream
	wg sync.WaitGroup

	// handler is the handler for the stream
	handler HandlerInterface

	// dispatcher is the dispatcher for the stream
	dispatcher *Dispatcher

	// writer is the writer for the stream
	writer *Writer

	// sender is the sender for the stream
	sender *Sender

	// settings is the settings for the stream
	settings *service.Settings

	// logger is the logger for the stream
	logger *observability.NexusLogger

	// inChan is the channel for incoming messages
	inChan chan *service.Record

	// loopbackChan is the channel for internal loopback messages
	loopbackChan chan *service.Record

	// internal responses from teardown path typically
	respChan chan *service.ServerResponse
}

// NewStream creates a new stream with the given settings and responders.
func NewStream(ctx context.Context, settings *service.Settings, streamId string) *Stream {
	logger := SetupStreamLogger(settings)

	ctx, cancel := context.WithCancel(ctx)

	s := &Stream{
		ctx:      ctx,
		cancel:   cancel,
		wg:       sync.WaitGroup{},
		settings: settings,
		logger:   logger,
		inChan:   make(chan *service.Record, BufferSize),
		respChan: make(chan *service.ServerResponse, BufferSize),
	}

	s.loopbackChan = make(chan *service.Record, BufferSize)
	s.handler = NewHandler(s.ctx, s.cancel, s.settings, s.logger)
	s.writer = NewWriter(s.ctx, s.cancel, s.settings, s.logger)
	s.sender = NewSender(s.ctx, s.cancel, s.settings, s.logger, s.loopbackChan)
	s.dispatcher = NewDispatcher(s.logger)

	s.logger.Info("created new stream", "id", s.settings.RunId)
	return s
}

// AddResponders adds the given responders to the stream's dispatcher.
func (s *Stream) AddResponders(entries ...ResponderEntry) {
	s.dispatcher.AddResponders(entries...)
}

func (s *Stream) SetHandler(handler HandlerInterface) {
	s.handler = handler
}

// Start starts the stream's handler, writer, sender, and dispatcher.
// We use Stream's wait group to ensure that all of these components are cleanly
// finalized and closed when the stream is closed in Stream.Close().
func (s *Stream) Start() {
	// handle the client requests with the handler
	s.handler.SetInboundChannels(s.inChan, s.loopbackChan)
	handlerFwdChan := make(chan *service.Record, BufferSize)
	handlerOutChan := make(chan *service.Result, BufferSize)
	s.handler.SetOutboundChannels(handlerFwdChan, handlerOutChan)
	s.wg.Add(1)
	go func() {
		s.handler.Run()
		s.wg.Done()
	}()

	// write the data to a transaction log
	s.wg.Add(1)
	go func() {
		s.writer.Run(handlerFwdChan)
		s.wg.Done()
	}()

	// send the data to the server
	s.wg.Add(1)
	go func() {
		s.sender.Run(s.writer.fwdChan)
		s.wg.Done()
	}()

	// handle dispatching between components
	s.wg.Add(1)
	go func() {
		s.dispatcher.Run(handlerOutChan, s.sender.outChan)
		s.wg.Done()
	}()

	// listen for the shutdown signal
	s.wg.Add(1)
	go func() {
		<-s.ctx.Done()
		s.wg.Done()
		s.Close()
	}()

	s.logger.Debug("starting stream", "id", s.settings.RunId)
}

// HandleRecord handles the given record by sending it to the stream's handler.
func (s *Stream) HandleRecord(rec *service.Record) {
	s.logger.Debug("handling record", "record", rec)
	s.inChan <- rec
}

func (s *Stream) GetRun() *service.RunRecord {
	return s.handler.GetRun()
}

// Close Gracefully wait for handler, writer, sender, dispatcher to shut down cleanly
// assumes an exit record has already been sent
func (s *Stream) Close() {
	s.handler.Close()
	s.writer.Close()
	s.sender.Close()
	s.wg.Wait()
}

// Respond Handle internal responses like from the finish and close path
func (s *Stream) Respond(resp *service.ServerResponse) {
	s.respChan <- resp
}

func (s *Stream) FinishAndClose(exitCode int32) {
	s.AddResponders(ResponderEntry{s, internalConnectionId})

	// send exit record to handler
	record := &service.Record{
		RecordType: &service.Record_Exit{
			Exit: &service.RunExitRecord{
				ExitCode: exitCode,
			}},
		Control: &service.Control{AlwaysSend: true, ConnectionId: internalConnectionId, ReqResp: true},
	}

	s.HandleRecord(record)
	// TODO(beta): process the response so we can formulate a more correct footer
	<-s.respChan

	// send a shutdown which triggers the handler to stop processing new records
	shutdownRecord := &service.Record{
		RecordType: &service.Record_Request{
			Request: &service.Request{
				RequestType: &service.Request_Shutdown{
					Shutdown: &service.ShutdownRequest{},
				},
			}},
		Control: &service.Control{AlwaysSend: true, ConnectionId: internalConnectionId, ReqResp: true},
	}
	s.HandleRecord(shutdownRecord)
	<-s.respChan

	s.cancel()

	s.PrintFooter()
	s.logger.Info("closed stream", "id", s.settings.RunId)
}

func (s *Stream) PrintFooter() {
	run := s.GetRun()
	shared.PrintHeadFoot(run, s.settings, true)
}
