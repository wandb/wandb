package server

import (
	"context"
	"sync"

	"github.com/wandb/wandb/nexus/pkg/service"
)

// Stream is a collection of components that work together to handle incoming
// data for a W&B run, store it locally, and send it to a W&B server.
// Stream.handler receives incoming data from the client and dispatches it to
// Stream.writer, which writes it to a local file. Stream.writer then sends the
// data to Stream.sender, which sends it to the W&B server. Stream.dispatcher
// handles dispatching responses to the appropriate client responders.
type Stream struct {
	handler    *Handler
	dispatcher *Dispatcher
	writer     *Writer
	sender     *Sender
	settings   *Settings
	finished   bool
	done       chan struct{}
}

func NewStream(settings *Settings) *Stream {
	ctx := context.Background()
	dispatcher := NewDispatcher(ctx)
	sender := NewSender(ctx, settings)
	writer := NewWriter(ctx, settings)
	handler := NewHandler(ctx, settings)

	// connect the components
	handler.outChan = writer.inChan
	writer.outChan = sender.inChan
	sender.outChan = handler.inChan

	// connect the dispatcher to the handler and sender
	handler.dispatcherChan = dispatcher
	sender.dispatcherChan = dispatcher

	stream := &Stream{
		dispatcher: dispatcher,
		handler:    handler,
		sender:     sender,
		writer:     writer,
		settings:   settings,
		done:       make(chan struct{}),
	}

	return stream

}

func (s *Stream) AddResponder(responderId string, responder Responder) {
	s.dispatcher.AddResponder(responderId, responder)
}

// Start starts the stream's handler, writer, sender, and dispatcher.
// We use Stream's wait group to ensure that all of these components are cleanly
// finalized and closed when the stream is closed in Stream.Close().
func (s *Stream) Start() {

	wg := &sync.WaitGroup{}

	// start the handler
	go s.handler.start()

	// start the writer
	wg.Add(1)
	go s.writer.start(wg)

	// start the sender
	wg.Add(1)
	go s.sender.start(wg)

	// start the dispatcher
	go s.dispatcher.start()

	wg.Wait()
	s.done <- struct{}{}
}

func (s *Stream) HandleRecord(rec *service.Record) {
	s.handler.inChan <- rec
}

func (s *Stream) MarkFinished() {
	s.finished = true
}

func (s *Stream) IsFinished() bool {
	return s.finished
}

func (s *Stream) GetSettings() *Settings {
	return s.settings
}

func (s *Stream) GetRun() *service.RunRecord {
	return s.handler.GetRun()
}

// Close closes the stream's handler, writer, sender, and dispatcher.
// We first mark the Stream's context as done, which signals to the
// components that they should close. Each of the components will
// call Done() on the Stream's wait group when they are finished closing.

func (s *Stream) Close(wg *sync.WaitGroup) {
	defer wg.Done()

	// todo: is this the best way to handle this?
	if s.IsFinished() {
		return
	}

	// send exit record to handler
	record := &service.Record{RecordType: &service.Record_Exit{Exit: &service.RunExitRecord{}}, Control: &service.Control{AlwaysSend: true}}
	s.HandleRecord(record)
	<-s.done

	settings := s.GetSettings()
	run := s.GetRun()
	PrintHeadFoot(run, settings)
	s.MarkFinished()
}
