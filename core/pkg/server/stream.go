package server

import (
	"context"
	"fmt"
	"io"
	"log/slog"
	"os"
	"path/filepath"
	"sync"
	"sync/atomic"
	"time"

	"github.com/Khan/genqlient/graphql"
	"github.com/wandb/wandb/core/internal/filestream"
	"github.com/wandb/wandb/core/internal/filetransfer"
	"github.com/wandb/wandb/core/internal/mailbox"
	"github.com/wandb/wandb/core/internal/runfiles"
	"github.com/wandb/wandb/core/internal/runsummary"
	"github.com/wandb/wandb/core/internal/sentry"
	"github.com/wandb/wandb/core/internal/settings"
	"github.com/wandb/wandb/core/internal/version"
	"github.com/wandb/wandb/core/internal/watcher"
	"github.com/wandb/wandb/core/pkg/monitor"
	"github.com/wandb/wandb/core/pkg/observability"
	"github.com/wandb/wandb/core/pkg/service"
	"github.com/wandb/wandb/core/pkg/utils"
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
	settings *settings.Settings

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

	// closed indicates if the inChan and loopBackChan are closed
	closed *atomic.Bool

	// sentryClient is the client used to report errors to sentry.io
	sentryClient *sentry.SentryClient
}

func streamLogger(settings *settings.Settings, sentryClient *sentry.SentryClient) *observability.CoreLogger {
	// TODO: when we add session concept re-do this to use user provided path
	targetPath := filepath.Join(settings.GetLogDir(), "debug-core.log")
	if path := defaultLoggerPath.Load(); path != nil {
		path := path.(string)
		// check path exists
		if _, err := os.Stat(path); !os.IsNotExist(err) {
			err := os.Symlink(path, targetPath)
			if err != nil {
				slog.Error("error creating symlink", "error", err)
			}
		}
	}

	var writers []io.Writer
	name := settings.GetInternalLogFile()
	file, err := os.OpenFile(name, os.O_APPEND|os.O_CREATE|os.O_WRONLY, 0666)
	if err != nil {
		slog.Error(fmt.Sprintf("error opening log file: %s", err))
	} else {
		writers = append(writers, file)
	}
	writer := io.MultiWriter(writers...)

	// TODO: add a log level to the settings
	level := slog.LevelInfo
	if os.Getenv("WANDB_CORE_DEBUG") != "" {
		level = slog.LevelDebug
	}

	opts := &slog.HandlerOptions{
		Level: level,
		// AddSource: true,
	}

	logger := observability.NewCoreLogger(
		slog.New(slog.NewJSONHandler(writer, opts)),
		observability.WithTags(observability.Tags{}),
		observability.WithCaptureMessage(sentryClient.CaptureMessage),
		observability.WithCaptureException(sentryClient.CaptureException),
	)
	logger.Info("using version", "core version", version.Version)
	logger.Info("created symlink", "path", targetPath)
	tags := observability.Tags{
		"run_id":  settings.GetRunID(),
		"run_url": settings.GetRunURL(),
		"project": settings.GetProject(),
		"entity":  settings.GetEntity(),
	}
	logger.SetTags(tags)

	return logger
}

// NewStream creates a new stream with the given settings and responders.
func NewStream(settings *settings.Settings, _ string, sentryClient *sentry.SentryClient) *Stream {
	ctx, cancel := context.WithCancel(context.Background())
	s := &Stream{
		ctx:          ctx,
		cancel:       cancel,
		logger:       streamLogger(settings, sentryClient),
		wg:           sync.WaitGroup{},
		settings:     settings,
		inChan:       make(chan *service.Record, BufferSize),
		loopBackChan: make(chan *service.Record, BufferSize),
		outChan:      make(chan *service.ServerResponse, BufferSize),
		closed:       &atomic.Bool{},
		sentryClient: sentryClient,
	}

	// TODO: replace this with a logger that can be read by the user
	peeker := &observability.Peeker{}
	terminalPrinter := observability.NewPrinter()

	backendOrNil := NewBackend(s.logger, settings)
	fileTransferStats := filetransfer.NewFileTransferStats()
	fileWatcher := watcher.New(watcher.Params{Logger: s.logger})
	var graphqlClientOrNil graphql.Client
	var fileStreamOrNil filestream.FileStream
	var fileTransferManagerOrNil filetransfer.FileTransferManager
	var runfilesUploaderOrNil runfiles.Uploader
	if backendOrNil != nil {
		graphqlClientOrNil = NewGraphQLClient(backendOrNil, settings, peeker)
		fileStreamOrNil = NewFileStream(
			backendOrNil,
			s.logger,
			terminalPrinter,
			settings,
			peeker,
		)
		fileTransferManagerOrNil = NewFileTransferManager(
			fileTransferStats,
			s.logger,
			settings,
		)
		runfilesUploaderOrNil = NewRunfilesUploader(
			s.ctx,
			s.logger,
			settings,
			fileStreamOrNil,
			fileTransferManagerOrNil,
			fileWatcher,
			graphqlClientOrNil,
		)
	}

	mailbox := mailbox.NewMailbox()

	s.handler = NewHandler(s.ctx,
		HandlerParams{
			Logger:            s.logger,
			Settings:          s.settings.Proto,
			FwdChan:           make(chan *service.Record, BufferSize),
			OutChan:           make(chan *service.Result, BufferSize),
			SystemMonitor:     monitor.NewSystemMonitor(s.logger, s.settings.Proto, s.loopBackChan),
			RunfilesUploader:  runfilesUploaderOrNil,
			TBHandler:         NewTBHandler(fileWatcher, s.logger, s.settings.Proto, s.loopBackChan),
			FileTransferStats: fileTransferStats,
			RunSummary:        runsummary.New(),
			MetricHandler:     NewMetricHandler(),
			Mailbox:           mailbox,
			TerminalPrinter:   terminalPrinter,
		},
	)

	s.writer = NewWriter(s.ctx,
		WriterParams{
			Logger:   s.logger,
			Settings: s.settings.Proto,
			FwdChan:  make(chan *service.Record, BufferSize),
		},
	)

	var outputFile string
	if settings.Proto.GetConsoleMultipart().GetValue() {
		outputFile = filepath.Join(
			"logs",
			fmt.Sprintf("%s_output.log", time.Now().Format("20060102_150405.000000")),
		)
	}
	s.sender = NewSender(
		s.ctx,
		s.cancel,
		SenderParams{
			Logger:              s.logger,
			Settings:            s.settings.Proto,
			Backend:             backendOrNil,
			FileStream:          fileStreamOrNil,
			FileTransferManager: fileTransferManagerOrNil,
			FileWatcher:         fileWatcher,
			RunfilesUploader:    runfilesUploaderOrNil,
			Peeker:              peeker,
			RunSummary:          runsummary.New(),
			GraphqlClient:       graphqlClientOrNil,
			FwdChan:             s.loopBackChan,
			OutChan:             make(chan *service.Result, BufferSize),
			Mailbox:             mailbox,
			OutputFileName:      outputFile,
		},
	)

	s.dispatcher = NewDispatcher(s.logger)

	s.logger.Info("created new stream", "id", s.settings.GetRunID())
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
	s.logger.Debug("starting stream", "id", s.settings.GetRunID())
}

// HandleRecord handles the given record by sending it to the stream's handler.
func (s *Stream) HandleRecord(rec *service.Record) {
	s.logger.Debug("handling record", "record", rec)
	if s.closed.Load() {
		// this is to prevent trying to process messages after the stream is closed
		s.logger.Error("context done, not handling record", "record", rec)
		return
	}
	s.inChan <- rec
}

// Close Gracefully wait for handler, writer, sender, dispatcher to shut down cleanly
// assumes an exit record has already been sent
func (s *Stream) Close() {
	// wait for the context to be canceled in the defer state machine in the sender
	<-s.ctx.Done()
	if !s.closed.Swap(true) {
		close(s.loopBackChan)
		close(s.inChan)
	}
	s.wg.Wait()
}

// Respond Handle internal responses like from the finish and close path
func (s *Stream) Respond(resp *service.ServerResponse) {
	s.outChan <- resp
}

// FinishAndClose closes the stream and sends an exit record to the handler.
// This will be called when we recieve a teardown signal from the client.
// So it is used to close all active streams in the system.
func (s *Stream) FinishAndClose(exitCode int32) {
	s.AddResponders(ResponderEntry{s, internalConnectionId})

	if !s.settings.IsSync() {
		// send exit record to handler
		record := &service.Record{
			RecordType: &service.Record_Exit{
				Exit: &service.RunExitRecord{
					ExitCode: exitCode,
				}},
			Control: &service.Control{AlwaysSend: true, ConnectionId: internalConnectionId, ReqResp: true},
		}

		s.HandleRecord(record)
		<-s.outChan
	}

	s.Close()

	// TODO: we are using service.Settings instead of settings.Settings
	// because this package is used by the go wandb client package
	if s.settings.IsOffline() {
		utils.PrintFooterOffline(s.settings.Proto)
	} else {
		run := s.handler.GetRun()
		utils.PrintFooterOnline(run, s.settings.Proto)
	}

	s.logger.Info("closed stream", "id", s.settings.GetRunID())
}
