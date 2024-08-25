package server

import (
	"fmt"
	"io"
	"log/slog"
	"os"
	"path/filepath"
	"sync"
	"time"

	"github.com/Khan/genqlient/graphql"
	"github.com/wandb/wandb/core/internal/filestream"
	"github.com/wandb/wandb/core/internal/filetransfer"
	"github.com/wandb/wandb/core/internal/mailbox"
	"github.com/wandb/wandb/core/internal/paths"
	"github.com/wandb/wandb/core/internal/runfiles"
	"github.com/wandb/wandb/core/internal/runsummary"
	"github.com/wandb/wandb/core/internal/runwork"
	"github.com/wandb/wandb/core/internal/sentry_ext"
	"github.com/wandb/wandb/core/internal/settings"
	"github.com/wandb/wandb/core/internal/tensorboard"
	"github.com/wandb/wandb/core/internal/version"
	"github.com/wandb/wandb/core/internal/watcher"
	"github.com/wandb/wandb/core/pkg/monitor"
	"github.com/wandb/wandb/core/pkg/observability"
	"github.com/wandb/wandb/core/pkg/utils"

	spb "github.com/wandb/wandb/core/pkg/service_go_proto"
)

// Stream processes incoming records for a single run.
//
// wandb consists of a service process (this code) to which one or more
// user processes connect (e.g. using the Python wandb library). The user
// processes send "records" to the service process that log to and modify
// the run, which the service process consumes asynchronously.
type Stream struct {
	// runWork is a channel of records to process.
	runWork runwork.RunWork

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

	// dispatcher is the dispatcher for the stream
	dispatcher *Dispatcher

	// sentryClient is the client used to report errors to sentry.io
	sentryClient *sentry_ext.Client
}

func streamLogger(settings *settings.Settings, sentryClient *sentry_ext.Client) *observability.CoreLogger {
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

	sentryClient.SetUser(
		settings.GetEntity(),
		settings.GetEmail(),
		settings.GetUserName(),
	)

	logger := observability.NewCoreLogger(
		slog.New(slog.NewJSONHandler(writer, opts)),
		observability.WithTags(observability.Tags{}),
		observability.WithCaptureMessage(sentryClient.CaptureMessage),
		observability.WithCaptureException(sentryClient.CaptureException),
		observability.WithReraise(sentryClient.Reraise),
	)
	logger.Info("using version", "core version", version.Version)
	logger.Info("created symlink", "path", targetPath)

	tags := observability.Tags{
		"run_id":   settings.GetRunID(),
		"run_url":  settings.GetRunURL(),
		"project":  settings.GetProject(),
		"base_url": settings.GetBaseURL(),
	}
	if settings.GetSweepURL() != "" {
		tags["sweep_url"] = settings.GetSweepURL()
	}
	logger.SetTags(tags)

	return logger
}

// NewStream creates a new stream with the given settings and responders.
func NewStream(
	commit string,
	settings *settings.Settings,
	sentryClient *sentry_ext.Client,
) *Stream {
	logger := streamLogger(settings, sentryClient)
	runWork := runwork.New(BufferSize, logger)

	s := &Stream{
		runWork:      runWork,
		logger:       streamLogger(settings, sentryClient),
		settings:     settings,
		sentryClient: sentryClient,
	}

	hostname, err := os.Hostname()
	if err != nil {
		// We log an error but continue anyway with an empty hostname string.
		// Better behavior would be to inform the user and turn off any
		// components that rely on the hostname, but it's not easy to do
		// with our current code structure.
		s.logger.CaptureError(
			fmt.Errorf("stream: could not get hostname: %v", err))
		hostname = ""
	}

	// TODO: replace this with a logger that can be read by the user
	peeker := &observability.Peeker{}
	terminalPrinter := observability.NewPrinter()

	backendOrNil := NewBackend(s.logger, settings)
	fileTransferStats := filetransfer.NewFileTransferStats()
	fileWatcher := watcher.New(watcher.Params{Logger: s.logger})
	tbHandler := tensorboard.NewTBHandler(tensorboard.Params{
		ExtraWork: s.runWork,
		Logger:    s.logger,
		Settings:  s.settings,
		Hostname:  hostname,
	})
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
			s.runWork,
			s.logger,
			settings,
			fileStreamOrNil,
			fileTransferManagerOrNil,
			fileWatcher,
			graphqlClientOrNil,
		)
	}

	mailbox := mailbox.New()

	s.handler = NewHandler(commit,
		HandlerParams{
			Logger:            s.logger,
			Settings:          s.settings.Proto,
			FwdChan:           make(chan *spb.Record, BufferSize),
			OutChan:           make(chan *spb.Result, BufferSize),
			SystemMonitor:     monitor.New(s.logger, s.settings.Proto, s.runWork),
			RunfilesUploader:  runfilesUploaderOrNil,
			TBHandler:         tbHandler,
			FileTransferStats: fileTransferStats,
			Mailbox:           mailbox,
			TerminalPrinter:   terminalPrinter,
		},
	)

	s.writer = NewWriter(
		WriterParams{
			Logger:   s.logger,
			Settings: s.settings.Proto,
			FwdChan:  make(chan *spb.Record, BufferSize),
		},
	)

	var outputFile *paths.RelativePath
	if settings.Proto.GetConsoleMultipart().GetValue() {
		// This is guaranteed not to fail.
		outputFile, _ = paths.Relative(
			filepath.Join(
				"logs",
				fmt.Sprintf(
					"%s_output.log",
					time.Now().Format("20060102_150405.000000"),
				),
			),
		)
	}

	s.sender = NewSender(
		s.runWork,
		SenderParams{
			Logger:              s.logger,
			Settings:            s.settings,
			Backend:             backendOrNil,
			FileStream:          fileStreamOrNil,
			FileTransferManager: fileTransferManagerOrNil,
			FileWatcher:         fileWatcher,
			RunfilesUploader:    runfilesUploaderOrNil,
			TBHandler:           tbHandler,
			Peeker:              peeker,
			RunSummary:          runsummary.New(),
			GraphqlClient:       graphqlClientOrNil,
			OutChan:             make(chan *spb.Result, BufferSize),
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
	// handle the client requests with the handler
	s.wg.Add(1)
	go func() {
		s.handler.Do(s.runWork.Chan())
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
	for _, ch := range []chan *spb.Result{s.handler.outChan, s.sender.outChan} {
		s.wg.Add(1)
		go func(ch chan *spb.Result) {
			for result := range ch {
				s.dispatcher.handleRespond(result)
			}
			s.wg.Done()
		}(ch)
	}

	s.logger.Info("stream: started", "id", s.settings.GetRunID())
}

// HandleRecord handles the given record by sending it to the stream's handler.
func (s *Stream) HandleRecord(rec *spb.Record) {
	s.logger.Debug("handling record", "record", rec)
	s.runWork.AddRecord(rec)
}

// Close waits for all run messages to be fully processed.
func (s *Stream) Close() {
	s.logger.Info("stream: closing", "id", s.settings.GetRunID())
	s.runWork.Close()
	s.wg.Wait()
	s.logger.Info("stream: closed", "id", s.settings.GetRunID())
}

// FinishAndClose emits an exit record, waits for all run messages
// to be fully processed, and prints the run footer to the terminal.
func (s *Stream) FinishAndClose(exitCode int32) {
	if !s.settings.IsSync() {
		s.HandleRecord(&spb.Record{
			RecordType: &spb.Record_Exit{
				Exit: &spb.RunExitRecord{
					ExitCode: exitCode,
				}},
			Control: &spb.Control{AlwaysSend: true},
		})
	}

	s.Close()

	if s.settings.IsOffline() {
		utils.PrintFooterOffline(s.settings.Proto)
	} else {
		run := s.handler.GetRun()
		utils.PrintFooterOnline(run, s.settings.Proto)
	}
}
