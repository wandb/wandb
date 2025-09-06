package stream

import (
	"fmt"
	"os"
	"path/filepath"
	"sync"
	"time"

	"github.com/Khan/genqlient/graphql"
	"github.com/wandb/wandb/core/internal/featurechecker"
	"github.com/wandb/wandb/core/internal/observability"
	"github.com/wandb/wandb/core/internal/pfxout"
	"github.com/wandb/wandb/core/internal/runwork"
	"github.com/wandb/wandb/core/internal/sentry_ext"
	"github.com/wandb/wandb/core/internal/settings"
	"github.com/wandb/wandb/core/internal/sharedmode"
	"github.com/wandb/wandb/core/internal/tensorboard"
	"github.com/wandb/wandb/core/internal/waiting"
	"github.com/wandb/wandb/core/internal/wboperation"

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

	// RecordParser turns Records into Work.
	recordParser RecordParser

	// handler is the handler for the stream
	handler *Handler

	// writer is the writer for the stream
	writer *Writer

	// flowControlFactory is used to create the FlowControl component
	flowControlFactory *FlowControlFactory

	// sender is the sender for the stream
	sender *Sender

	// dispatcher is the dispatcher for the stream
	dispatcher *Dispatcher

	// sentryClient is the client used to report errors to sentry.io
	sentryClient *sentry_ext.Client

	// clientID is a unique ID for the stream
	clientID sharedmode.ClientID
}

// DebugCorePath is the absolute path to the debug-core.log file.
type DebugCorePath string

// NewStream creates a new stream.
func NewStream(
	clientID sharedmode.ClientID,
	debugCorePath DebugCorePath,
	featureProvider *featurechecker.ServerFeaturesCache,
	flowControlFactory *FlowControlFactory,
	graphqlClientOrNil graphql.Client,
	handlerFactory *HandlerFactory,
	loggerFile streamLoggerFile,
	logger *observability.CoreLogger,
	operations *wboperation.WandbOperations,
	recordParserFactory *RecordParserFactory,
	senderFactory *SenderFactory,
	sentry *sentry_ext.Client,
	settings *settings.Settings,
	streamRun *StreamRun,
	tbHandlerFactory *tensorboard.TBHandlerFactory,
	writerFactory *WriterFactory,
) *Stream {
	symlinkDebugCore(settings, string(debugCorePath))

	runWork := runwork.New(BufferSize, logger)
	tbHandler := tbHandlerFactory.New(
		runWork,
		/*fileReadDelay=*/ waiting.NewDelay(5*time.Second),
	)
	recordParser := recordParserFactory.New(runWork.BeforeEndCtx(), tbHandler)

	s := &Stream{
		runWork:            runWork,
		run:                streamRun,
		operations:         operations,
		featureProvider:    featureProvider,
		graphqlClientOrNil: graphqlClientOrNil,
		logger:             logger,
		loggerFile:         loggerFile,
		settings:           settings,
		recordParser:       recordParser,
		handler:            handlerFactory.New(runWork),
		flowControlFactory: flowControlFactory,
		sender:             senderFactory.New(runWork),
		sentryClient:       sentry,
		clientID:           clientID,
	}

	switch {
	case s.settings.IsSync():
		s.reader = NewReader(ReaderParams{
			Logger:   logger,
			Settings: s.settings,
			RunWork:  runWork,
		})
	case !s.settings.IsSkipTransactionLog():
		s.writer = writerFactory.New()
	default:
		logger.Info("stream: not syncing, skipping transaction log",
			"id", s.settings.GetRunID(),
		)
	}

	s.dispatcher = NewDispatcher(logger)

	logger.Info("stream: created new stream", "id", s.settings.GetRunID())
	return s
}

// AddResponders adds the given responders to the stream's dispatcher.
func (s *Stream) AddResponders(entries ...ResponderEntry) {
	s.dispatcher.AddResponders(entries...)
}

// GetSettings returns the stream's settings.
func (s *Stream) GetSettings() *settings.Settings {
	return s.settings
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
			s.sender.Do(s.handler.OutChan())
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
			s.sender.Do(s.handler.OutChan())
			s.wg.Done()
		}()

	default:
		// The default case: we write all records to the transaction log
		// and forward them to the sender.
		flowControl := s.flowControlFactory.New(
			s.settings.GetTransactionLogPath(),
			s.writer.Flush,
			s.recordParser,
		)

		s.wg.Add(1)
		go func() {
			s.writer.Do(s.handler.OutChan())
			s.wg.Done()
		}()

		s.wg.Add(1)
		go func() {
			flowControl.Do(s.writer.Chan())
			s.wg.Done()
		}()

		s.wg.Add(1)
		go func() {
			s.sender.Do(flowControl.Chan())
			s.wg.Done()
		}()
	}

	// handle dispatching between components
	for _, ch := range []<-chan *spb.Result{
		s.handler.ResponseChan(),
		s.sender.ResponseChan(),
	} {
		s.wg.Add(1)
		go func(ch <-chan *spb.Result) {
			for result := range ch {
				s.dispatcher.handleRespond(result)
			}
			s.wg.Done()
		}(ch)
	}

	s.logger.Info("stream: started", "id", s.settings.GetRunID())
}

// HandleRecord ingests a record from the client.
func (s *Stream) HandleRecord(record *spb.Record) {
	s.logger.Debug("handling record", "record", record.GetRecordType())
	work := s.recordParser.Parse(record)
	work.Schedule(&sync.WaitGroup{}, func() { s.runWork.AddWork(work) })
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
