package stream

import (
	"context"
	"fmt"
	"io"
	"log/slog"
	"os"
	"path/filepath"
	"sync"

	"github.com/wandb/wandb/core/internal/lib/shared"
	"github.com/wandb/wandb/core/internal/monitor"
	"github.com/wandb/wandb/core/internal/observability"
	"github.com/wandb/wandb/core/internal/server/stream/handler"
	"github.com/wandb/wandb/core/internal/server/stream/sender"
	"github.com/wandb/wandb/core/internal/version"
	pb "github.com/wandb/wandb/core/internal/wandb_core_go_proto"
	"github.com/wandb/wandb/core/internal/watcher"
)

const (
	internalConnectionId = "internal"
	BufferSize           = 32
)

func SetupStreamLogger(settings *pb.Settings) *observability.CoreLogger {
	// TODO: when we add session concept re-do this to use user provided path
	targetPath := filepath.Join(settings.GetLogDir().GetValue(), "core-debug.log")
	if path, ok := observability.GetDefaultLoggerPath(); ok {
		// check path exists
		if _, err := os.Stat(path); !os.IsNotExist(err) {
			err := os.Symlink(path, targetPath)
			if err != nil {
				slog.Error("error creating symlink", "error", err)
			}
		}
	}

	var writers []io.Writer
	name := settings.GetLogInternal().GetValue()

	file, err := os.OpenFile(name, os.O_APPEND|os.O_CREATE|os.O_WRONLY, 0666)
	if err != nil {
		slog.Error(fmt.Sprintf("error opening log file: %s", err))
	} else {
		writers = append(writers, file)
	}
	// TODO: add it into settings
	level := slog.LevelInfo
	if os.Getenv("WANDB_CORE_DEBUG") != "" {
		writers = append(writers, os.Stderr)
		level = slog.LevelDebug
	}
	writer := io.MultiWriter(writers...)
	opts := &slog.HandlerOptions{
		Level: level,
	}
	logger := observability.NewCoreLogger(
		slog.New(slog.NewJSONHandler(writer, opts)),
		observability.WithTags(observability.Tags{}),
		observability.WithCaptureMessage(observability.CaptureMessage),
		observability.WithCaptureException(observability.CaptureException),
	)
	logger.Info("using version", "core version", version.Version)
	logger.Info("created symlink", "path", targetPath)
	tags := observability.Tags{
		"run_id":  settings.GetRunId().GetValue(),
		"run_url": settings.GetRunUrl().GetValue(),
		"project": settings.GetProject().GetValue(),
		"entity":  settings.GetEntity().GetValue(),
	}
	logger.SetTags(tags)

	return logger
}

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

	// Logger is the Logger for the stream
	Logger *observability.CoreLogger

	// wg is the WaitGroup for the stream
	wg sync.WaitGroup

	// Settings is the Settings for the stream
	Settings *pb.Settings

	// handler is the handler for the stream
	handler *handler.Handler

	// writer is the writer for the stream
	writer *Writer

	// sender is the sender for the stream
	sender *sender.Sender

	// inChan is the channel for incoming messages
	inChan chan *pb.Record

	// loopBackChan is the channel for internal loopback messages
	loopBackChan chan *pb.Record

	// internal responses from teardown path typically
	outChan chan *pb.ServerResponse

	// dispatcher is the dispatcher for the stream
	dispatcher *Dispatcher
}

// NewStream creates a new stream with the given settings and responders.
func NewStream(ctx context.Context, settings *pb.Settings, streamId string) *Stream {
	ctx, cancel := context.WithCancel(ctx)
	s := &Stream{
		ctx:          ctx,
		cancel:       cancel,
		Logger:       SetupStreamLogger(settings),
		wg:           sync.WaitGroup{},
		Settings:     settings,
		inChan:       make(chan *pb.Record, BufferSize),
		loopBackChan: make(chan *pb.Record, BufferSize),
		outChan:      make(chan *pb.ServerResponse, BufferSize),
	}

	watcher := watcher.New(watcher.WithLogger(s.Logger))
	s.handler = handler.NewHandler(s.ctx, s.Logger,
		handler.WithHandlerSettings(s.Settings),
		handler.WithHandlerFwdChannel(make(chan *pb.Record, BufferSize)),
		handler.WithHandlerOutChannel(make(chan *pb.Result, BufferSize)),
		handler.WithHandlerSystemMonitor(monitor.NewSystemMonitor(s.Logger, s.Settings, s.loopBackChan)),
		handler.WithHandlerFileHandler(handler.NewFiles(watcher, s.Logger, s.Settings)),
		handler.WithHandlerTBHandler(handler.NewTensorBoard(watcher, s.Logger, s.Settings, s.loopBackChan)),
		handler.WithHandlerFilesInfoHandler(handler.NewFilesInfo()),
		handler.WithHandlerSummaryHandler(handler.NewSummary(s.Logger)),
		handler.WithHandlerMetricHandler(handler.NewMetrics()),
		handler.WithHandlerWatcher(watcher),
	)

	s.writer = NewWriter(s.ctx, s.Logger,
		WithWriterSettings(s.Settings),
		WithWriterFwdChannel(make(chan *pb.Record, BufferSize)),
	)

	s.sender = sender.NewSender(s.ctx, s.cancel, s.Logger, s.Settings,
		sender.WithSenderFwdChannel(s.loopBackChan),
		sender.WithSenderOutChannel(make(chan *pb.Result, BufferSize)),
	)

	s.dispatcher = NewDispatcher(s.Logger)

	s.Logger.Info("created new stream", "id", s.Settings.RunId)
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
	fwdChan := make(chan *pb.Record, BufferSize)
	s.wg.Add(1)
	go func() {
		wg := sync.WaitGroup{}
		for _, ch := range []chan *pb.Record{s.inChan, s.loopBackChan} {
			wg.Add(1)
			go func(ch chan *pb.Record) {
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
		s.writer.Do(s.handler.FwdChan)
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
		for _, ch := range []chan *pb.Result{s.handler.OutChan, s.sender.OutChan} {
			wg.Add(1)
			go func(ch chan *pb.Result) {
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
	s.Logger.Debug("starting stream", "id", s.Settings.RunId)
}

// HandleRecord handles the given record by sending it to the stream's handler.
func (s *Stream) HandleRecord(rec *pb.Record) {
	s.Logger.Debug("handling record", "record", rec)
	s.inChan <- rec
}

func (s *Stream) GetRun() *pb.RunRecord {
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
func (s *Stream) Respond(resp *pb.ServerResponse) {
	s.outChan <- resp
}

func (s *Stream) FinishAndClose(exitCode int32) {
	s.AddResponders(ResponderEntry{s, internalConnectionId})

	if !s.Settings.GetXSync().GetValue() {
		// send exit record to handler
		record := &pb.Record{
			RecordType: &pb.Record_Exit{
				Exit: &pb.RunExitRecord{
					ExitCode: exitCode,
				}},
			Control: &pb.Control{AlwaysSend: true, ConnectionId: internalConnectionId, ReqResp: true},
		}

		s.HandleRecord(record)
		// TODO(beta): process the response so we can formulate a more correct footer
		<-s.outChan
	}

	s.Close()

	s.PrintFooter()
	s.Logger.Info("closed stream", "id", s.Settings.RunId)
}

func (s *Stream) PrintFooter() {
	run := s.GetRun()
	shared.PrintHeadFoot(run, s.Settings, true)
}
