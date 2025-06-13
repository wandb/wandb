package stream

import (
	"fmt"
	"io"
	"log/slog"
	"os"
	"path/filepath"
	"sync"

	"github.com/Khan/genqlient/graphql"
	"github.com/wandb/wandb/core/internal/featurechecker"
	"github.com/wandb/wandb/core/internal/filestream"
	"github.com/wandb/wandb/core/internal/filetransfer"
	"github.com/wandb/wandb/core/internal/mailbox"
	"github.com/wandb/wandb/core/internal/observability"
	"github.com/wandb/wandb/core/internal/pfxout"
	"github.com/wandb/wandb/core/internal/randomid"
	"github.com/wandb/wandb/core/internal/runfiles"
	"github.com/wandb/wandb/core/internal/runsummary"
	"github.com/wandb/wandb/core/internal/runupserter"
	"github.com/wandb/wandb/core/internal/runwork"
	"github.com/wandb/wandb/core/internal/sentry_ext"
	"github.com/wandb/wandb/core/internal/settings"
	"github.com/wandb/wandb/core/internal/tensorboard"
	"github.com/wandb/wandb/core/internal/version"
	"github.com/wandb/wandb/core/internal/watcher"
	"github.com/wandb/wandb/core/internal/wboperation"
	"github.com/wandb/wandb/core/pkg/monitor"

	spb "github.com/wandb/wandb/core/pkg/service_go_proto"
)

const BufferSize = 32

// Stream processes incoming records for a single run.
//
// wandb consists of a service process (this code) to which one or more
// user processes connect (e.g. using the Python wandb library). The user
// processes send "records" to the service process that log to and modify
// the run, which the service process consumes asynchronously.
type Stream struct {
	// runWork is a channel of records to process.
	runWork runwork.RunWork

	// run is the state of the run controlled by this stream.
	run *StreamRun

	// operations tracks the status of asynchronous work.
	operations *wboperation.WandbOperations

	// featureProvider checks server capabilities.
	featureProvider *featurechecker.ServerFeaturesCache

	// graphqlClientOrNil is used for GraphQL operations to the W&B backend.
	//
	// It is nil for offline runs.
	graphqlClientOrNil graphql.Client

	// logger writes debug logs for the run.
	logger *observability.CoreLogger

	// loggerFile is the file (if any) to which the logger writes.
	loggerFile *os.File

	// wg is the WaitGroup for the stream
	wg sync.WaitGroup

	// settings is the settings for the stream
	settings *settings.Settings

	// reader is the reader for the stream
	reader *Reader

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

// symlinkDebugCore symlinks the debug-core.log file to the run's directory.
func symlinkDebugCore(
	settings *settings.Settings,
	loggerPath string,
) {
	if loggerPath == "" {
		return
	}

	targetPath := filepath.Join(settings.GetLogDir(), "debug-core.log")

	err := os.Symlink(loggerPath, targetPath)
	if err != nil {
		slog.Error(
			"error symlinking debug-core.log",
			"loggerPath", loggerPath,
			"targetPath", targetPath,
			"error", err)
	}
}

// streamLoggerFile returns the file to use for logging.
func streamLoggerFile(settings *settings.Settings) *os.File {
	path := settings.GetInternalLogFile()
	loggerFile, err := os.OpenFile(path, os.O_APPEND|os.O_CREATE|os.O_WRONLY, 0666)

	if err != nil {
		slog.Error(
			"error opening log file",
			"path", path,
			"error", err)
		return nil
	} else {
		return loggerFile
	}
}

func streamLogger(
	loggerFile *os.File,
	settings *settings.Settings,
	sentryClient *sentry_ext.Client,
	logLevel slog.Level,
) *observability.CoreLogger {
	sentryClient.SetUser(
		settings.GetEntity(),
		settings.GetEmail(),
		settings.GetUserName(),
	)

	var writer io.Writer
	if loggerFile != nil {
		writer = loggerFile
	} else {
		writer = io.Discard
	}

	logger := observability.NewCoreLogger(
		slog.New(slog.NewJSONHandler(
			writer,
			&slog.HandlerOptions{
				Level: logLevel,
				// AddSource: true,
			},
		)),
		&observability.CoreLoggerParams{
			Tags:   observability.Tags{},
			Sentry: sentryClient,
		},
	)

	logger.Info(
		"stream: starting",
		"core version", version.Version)

	tags := observability.Tags{
		"run_id":   settings.GetRunID(),
		"run_url":  settings.GetRunURL(),
		"project":  settings.GetProject(),
		"base_url": settings.GetBaseURL(),
	}
	if settings.GetSweepURL() != "" {
		tags["sweep_url"] = settings.GetSweepURL()
	}
	logger.SetGlobalTags(tags)

	return logger
}

type StreamParams struct {
	Commit     string
	Settings   *settings.Settings
	Sentry     *sentry_ext.Client
	LoggerPath string
	LogLevel   slog.Level

	GPUResourceManager *monitor.GPUResourceManager
}

// NewStream creates a new stream with the given settings and responders.
func NewStream(
	params StreamParams,
) *Stream {
	symlinkDebugCore(params.Settings, params.LoggerPath)
	loggerFile := streamLoggerFile(params.Settings)
	logger := streamLogger(
		loggerFile,
		params.Settings,
		params.Sentry,
		params.LogLevel,
	)

	s := &Stream{
		runWork:      runwork.New(BufferSize, logger),
		run:          NewStreamRun(),
		operations:   wboperation.NewOperations(),
		logger:       logger,
		loggerFile:   loggerFile,
		settings:     params.Settings,
		sentryClient: params.Sentry,
	}
	clientId := randomid.GenerateUniqueID(32)

	// TODO: replace this with a logger that can be read by the user
	peeker := &observability.Peeker{}
	terminalPrinter := observability.NewPrinter()

	backendOrNil := NewBackend(s.logger, params.Settings)
	fileTransferStats := filetransfer.NewFileTransferStats()
	fileWatcher := watcher.New(watcher.Params{Logger: s.logger})
	tbHandler := tensorboard.NewTBHandler(tensorboard.Params{
		ExtraWork: s.runWork,
		Logger:    s.logger,
		Settings:  s.settings,
	})
	var fileStreamOrNil filestream.FileStream
	var fileTransferManagerOrNil filetransfer.FileTransferManager
	var runfilesUploaderOrNil runfiles.Uploader
	if backendOrNil != nil {
		s.graphqlClientOrNil = NewGraphQLClient(
			backendOrNil,
			params.Settings,
			peeker,
			clientId,
		)
		fileStreamOrNil = NewFileStream(
			backendOrNil,
			s.logger,
			s.operations,
			terminalPrinter,
			params.Settings,
			peeker,
			clientId,
		)
		fileTransferManagerOrNil = NewFileTransferManager(
			fileTransferStats,
			s.logger,
			params.Settings,
		)
		runfilesUploaderOrNil = NewRunfilesUploader(
			s.runWork,
			s.logger,
			s.operations,
			params.Settings,
			fileStreamOrNil,
			fileTransferManagerOrNil,
			fileWatcher,
			s.graphqlClientOrNil,
		)
	}

	s.featureProvider = featurechecker.NewServerFeaturesCache(
		s.runWork.BeforeEndCtx(),
		s.graphqlClientOrNil,
		s.logger,
	)

	mailbox := mailbox.New()
	switch {
	case s.settings.IsSync():
		s.reader = NewReader(ReaderParams{
			Logger:   s.logger,
			Settings: s.settings,
			RunWork:  s.runWork,
		})
	case !s.settings.IsSkipTransactionLog():
		s.writer = NewWriter(WriterParams{
			Logger:   s.logger,
			Settings: s.settings,
			FwdChan:  make(chan runwork.Work, BufferSize),
		})
	default:
		s.logger.Info("stream: not syncing, skipping transaction log",
			"id", s.settings.GetRunID(),
		)
	}

	s.handler = NewHandler(
		HandlerParams{
			Commit:            params.Commit,
			FileTransferStats: fileTransferStats,
			FwdChan:           make(chan runwork.Work, BufferSize),
			Logger:            s.logger,
			Mailbox:           mailbox,
			Operations:        s.operations,
			OutChan:           make(chan *spb.Result, BufferSize),
			Settings:          s.settings,
			SystemMonitor: monitor.NewSystemMonitor(monitor.SystemMonitorParams{
				Ctx:                s.runWork.BeforeEndCtx(),
				Logger:             s.logger,
				Settings:           s.settings,
				ExtraWork:          s.runWork,
				GpuResourceManager: params.GPUResourceManager,
				GraphqlClient:      s.graphqlClientOrNil,
			}),
			TBHandler:       tbHandler,
			TerminalPrinter: terminalPrinter,
		},
	)

	s.sender = NewSender(
		SenderParams{
			Logger:              s.logger,
			Operations:          s.operations,
			Settings:            s.settings,
			Backend:             backendOrNil,
			FileStream:          fileStreamOrNil,
			FileTransferManager: fileTransferManagerOrNil,
			FileTransferStats:   fileTransferStats,
			FileWatcher:         fileWatcher,
			RunfilesUploader:    runfilesUploaderOrNil,
			TBHandler:           tbHandler,
			Peeker:              peeker,
			StreamRun:           s.run,
			RunSummary:          runsummary.New(),
			GraphqlClient:       s.graphqlClientOrNil,
			OutChan:             make(chan *spb.Result, BufferSize),
			Mailbox:             mailbox,
			RunWork:             s.runWork,
			FeatureProvider:     s.featureProvider,
		},
	)

	s.dispatcher = NewDispatcher(s.logger)

	s.logger.Info("stream: created new stream", "id", s.settings.GetRunID())
	return s
}

// AddResponders adds the given responders to the stream's dispatcher.
func (s *Stream) AddResponders(entries ...ResponderEntry) {
	s.dispatcher.AddResponders(entries...)
}

// UpdateSettings updates the stream's settings with the given settings.
func (s *Stream) UpdateSettings(newSettings *settings.Settings) {
	s.settings = newSettings
}

// GetSettings returns the stream's settings.
func (s *Stream) GetSettings() *settings.Settings {
	return s.settings
}

// UpdateRunURLTag updates the run URL tag in the stream's logger.
// TODO: this should be removed when we remove informStart.
func (s *Stream) UpdateRunURLTag() {
	s.logger.SetGlobalTags(observability.Tags{
		"run_url": s.settings.GetRunURL(),
	})
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

	// different modes of operations depending on the settings
	switch {
	case s.settings.IsSkipTransactionLog():
		// if we are skipping the transaction log, we just forward the data from
		// the handler to the sender directly
		s.wg.Add(1)
		go func() {
			s.sender.Do(s.handler.fwdChan)
			s.wg.Done()
		}()
	case s.settings.IsSync():
		// if we are syncing, we need to read the data from the transaction log
		// and forward it to the handler, that will forward it to the sender
		// without going through the writer
		s.wg.Add(1)
		go func() {
			s.reader.Do()
			s.wg.Done()
		}()

		s.wg.Add(1)
		go func() {
			s.sender.Do(s.handler.fwdChan)
			s.wg.Done()
		}()
	default:
		// This is the default case, where we are not skipping the transaction log
		// and we are not syncing. We only get the data from the client and the
		// handler handles it passing it to the writer (storing in the transaction log),
		// that will forward it to the sender
		s.wg.Add(1)
		go func() {
			s.writer.Do(s.handler.fwdChan)
			s.wg.Done()
		}()

		s.wg.Add(1)
		go func() {
			s.sender.Do(s.writer.fwdChan)
			s.wg.Done()
		}()
	}

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
func (s *Stream) HandleRecord(record *spb.Record) {
	s.logger.Debug("handling record", "record", record.GetRecordType())

	var work runwork.Work

	if record.GetRun() != nil {
		work = &runupserter.RunUpdateWork{
			Record: record,

			StreamRunUpserter: s.run,
			Respond: func(record *spb.Record, result *spb.RunUpdateResult) {
				// Write to the sender's output channel because this is called
				// in the Sender goroutine.
				s.sender.outChan <- &spb.Result{
					ResultType: &spb.Result_RunResult{
						RunResult: result,
					},
					Control: record.Control,
					Uuid:    record.Uuid,
				}
			},

			Settings:           s.settings,
			BeforeRunEndCtx:    s.runWork.BeforeEndCtx(),
			Operations:         s.operations,
			FeatureProvider:    s.featureProvider,
			GraphqlClientOrNil: s.graphqlClientOrNil,
			Logger:             s.logger,
		}
	} else {
		// Legacy style for handling records where the code to process them
		// lives in handler.go and sender.go directly.
		work = runwork.WorkFromRecord(record)
	}

	s.runWork.AddWork(work)
}

// Close waits for all run messages to be fully processed.
func (s *Stream) Close() {
	s.logger.Info("stream: closing", "id", s.settings.GetRunID())
	s.runWork.Close()
	s.wg.Wait()
	s.logger.Info("stream: closed", "id", s.settings.GetRunID())

	if s.loggerFile != nil {
		// Sync the file instead of closing it, in case we keep writing to it.
		_ = s.loggerFile.Sync()
	}
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

	printFooter(s.settings)
}

func printFooter(settings *settings.Settings) {
	// Silent mode disables any footer output
	if settings.IsSilent() {
		return
	}

	formatter := pfxout.New(
		pfxout.WithColor("wandb", pfxout.BrightBlue),
	)

	formatter.Println("")
	if settings.IsOffline() {
		formatter.Println("You can sync this run to the cloud by running:")
		formatter.Println(
			pfxout.WithStyle(
				fmt.Sprintf("wandb sync %v", settings.GetSyncDir()),
				pfxout.Bold,
			),
		)
	} else {
		formatter.Println(
			fmt.Sprintf(
				"🚀 View run %v at: %v",
				pfxout.WithColor(settings.GetDisplayName(), pfxout.Yellow),
				pfxout.WithColor(settings.GetRunURL(), pfxout.Blue),
			),
		)
	}

	currentDir, err := os.Getwd()
	if err != nil {
		return
	}
	relLogDir, err := filepath.Rel(currentDir, settings.GetLogDir())
	if err != nil {
		return
	}
	formatter.Println(
		fmt.Sprintf(
			"Find logs at: %v",
			pfxout.WithColor(relLogDir, pfxout.BrightMagenta),
		),
	)
}
