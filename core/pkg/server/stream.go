package server

import (
	"context"
	"sync"

	"github.com/wandb/wandb/core/internal/shared"
	"github.com/wandb/wandb/core/pkg/monitor"
	"github.com/wandb/wandb/core/pkg/observability"
	"github.com/wandb/wandb/core/pkg/service"
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

	// logger is the logger for the stream
	logger *observability.CoreLogger

	// wg is the WaitGroup for the stream
	wg sync.WaitGroup

	// settings is the settings for the stream
	settings *service.Settings

	// handler is the handler for the stream
	handler *Handler

	// writer is the writer for the stream
	writer *Writer

	// sender is the sender for the stream
	sender *Sender

	// inChan is the channel for incoming messages
	inChan chan *service.Record

	// loopBackChan is the channel for internal loopback messages
	loopBackChan chan *service.Record

	// internal responses from teardown path typically
	outChan chan *service.ServerResponse

	// dispatcher is the dispatcher for the stream
	dispatcher *Dispatcher
}

// NewStream creates a new stream with the given settings and responders.
func NewStream(ctx context.Context, settings *service.Settings, streamId string) *Stream {
	ctx, cancel := context.WithCancel(ctx)
	s := &Stream{
		ctx:          ctx,
		cancel:       cancel,
		logger:       SetupStreamLogger(settings),
		wg:           sync.WaitGroup{},
		settings:     settings,
		inChan:       make(chan *service.Record, BufferSize),
		loopBackChan: make(chan *service.Record, BufferSize),
		outChan:      make(chan *service.ServerResponse, BufferSize),
	}

	s.handler = NewHandler(s.ctx, s.logger,
		WithHandlerSettings(s.settings),
		WithHandlerFwdChannel(make(chan *service.Record, BufferSize)),
		WithHandlerOutChannel(make(chan *service.Result, BufferSize)),
		WithHandlerSystemMonitor(monitor.NewSystemMonitor(s.settings, s.logger, s.loopBackChan)),
		WithHandlerFileHandler(NewFileHandler(s.logger, s.loopBackChan)),
		WithHandlerFileTransferHandler(NewFileTransferHandler()),
		WithHandlerSummaryHandler(NewSummaryHandler(s.logger)),
		WithHandlerMetricHandler(NewMetricHandler()),
	)

	s.writer = NewWriter(s.ctx, s.logger,
		WithWriterSettings(s.settings),
		WithWriterFwdChannel(make(chan *service.Record, BufferSize)),
	)

	s.sender = NewSender(s.ctx, s.cancel, s.logger, s.settings,
		WithSenderFwdChannel(s.loopBackChan),
		WithSenderOutChannel(make(chan *service.Result, BufferSize)),
	)

	s.dispatcher = NewDispatcher(s.logger)

	s.logger.Info("created new stream", "id", s.settings.RunId)
	return s
}

// AddResponders adds the given responders to the stream's dispatcher.
func (s *Stream) AddResponders(entries ...ResponderEntry) {
	s.dispatcher.AddResponders(entries...)
}

// Start starts the stream's handler, writer, sender, and dispatcher.
// We use Stream's wait group to ensure that all of these components are cleanly
// finalized and closed when the stream is closed in Stream.Close().
func (s *Stream) Start() {

	// forward records from the inChan and loopBackChan to the handler
	fwdChan := make(chan *service.Record, BufferSize)
	s.wg.Add(1)
	go func() {
		wg := sync.WaitGroup{}
		for _, ch := range []chan *service.Record{s.inChan, s.loopBackChan} {
			wg.Add(1)
			go func(ch chan *service.Record) {
				for record := range ch {
					fwdChan <- record
				}
				wg.Done()
			}(ch)
		}
		wg.Wait()
		close(fwdChan)
		s.wg.Done()
	}()

	// handle the client requests with the handler
	s.wg.Add(1)
	go func() {
		s.handler.Do(fwdChan)
		s.wg.Done()
	}()

	// write the data to a transaction log
	s.wg.Add(1)
	go func() {
		s.writer.Do(s.handler.fwdChan)
		s.wg.Done()
	}()

	// send the data to the server
	s.wg.Add(1)
	go func() {
		s.sender.Do(s.writer.fwdChan)
		s.wg.Done()
	}()

	// handle dispatching between components
	s.wg.Add(1)
	go func() {
		wg := sync.WaitGroup{}
		for _, ch := range []chan *service.Result{s.handler.outChan, s.sender.outChan} {
			wg.Add(1)
			go func(ch chan *service.Result) {
				for result := range ch {
					s.dispatcher.handleRespond(result)
				}
				wg.Done()
			}(ch)
		}
		wg.Wait()
		close(s.outChan)
		s.wg.Done()
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
	// wait for the context to be canceled in the defer state machine in the sender
	<-s.ctx.Done()
	close(s.loopBackChan)
	close(s.inChan)
	s.wg.Wait()
}

// Respond Handle internal responses like from the finish and close path
func (s *Stream) Respond(resp *service.ServerResponse) {
	s.outChan <- resp
}

func (s *Stream) FinishAndClose(exitCode int32) {
	s.AddResponders(ResponderEntry{s, internalConnectionId})

	if !s.settings.GetXSync().GetValue() {
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
		<-s.outChan
	}

	s.Close()

	s.PrintFooter()
	s.logger.Info("closed stream", "id", s.settings.RunId)
}

func (s *Stream) PrintFooter() {
	run := s.GetRun()
	shared.PrintHeadFoot(run, s.settings, true)
}
