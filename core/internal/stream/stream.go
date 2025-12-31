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
	"github.com/wandb/wandb/core/internal/runhandle"
	"github.com/wandb/wandb/core/internal/runwork"
	"github.com/wandb/wandb/core/internal/sentry_ext"
	"github.com/wandb/wandb/core/internal/settings"
	"github.com/wandb/wandb/core/internal/sharedmode"
	"github.com/wandb/wandb/core/internal/tensorboard"
	"github.com/wandb/wandb/core/internal/transactionlog"
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

	// runHandle is run info initialized after the first RunRecord.
	runHandle *runhandle.RunHandle

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

	// RecordParser turns Records into Work.
	recordParser RecordParser

	// handler is the handler for the stream
	handler *Handler

	// writerFactory is used to create the Writer component
	writerFactory *WriterFactory

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
	runHandle *runhandle.RunHandle,
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
		runHandle:          runHandle,
		operations:         operations,
		featureProvider:    featureProvider,
		graphqlClientOrNil: graphqlClientOrNil,
		logger:             logger,
		loggerFile:         loggerFile,
		settings:           settings,
		recordParser:       recordParser,
		handler:            handlerFactory.New(runWork),
		writerFactory:      writerFactory,
		flowControlFactory: flowControlFactory,
		sender:             senderFactory.New(runWork),
		sentryClient:       sentry,
		clientID:           clientID,
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

// Start begins processing the stream's input records and producing outputs.
func (s *Stream) Start() {
	s.wg.Add(1)
	go func() {
		s.handler.Do(s.runWork.Chan())
		s.wg.Done()
	}()

	maybeSavedWork := s.maybeSavingToTransactionLog(s.handler.OutChan())

	s.wg.Add(1)
	go func() {
		s.sender.Do(maybeSavedWork)
		s.wg.Done()
	}()

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

// maybeSavingToTransactionLog saves work from the channel into a transaction
// log if allowed by settings.
//
// The output is work that has been saved.
func (s *Stream) maybeSavingToTransactionLog(
	work <-chan runwork.Work,
) <-chan runwork.Work {
	if s.settings.IsSkipTransactionLog() {
		s.logger.Info(
			"stream: skipping transaction log due to settings",
			"id", s.settings.GetRunID())
		return work
	}

	w, err := transactionlog.OpenWriter(s.settings.GetTransactionLogPath())
	if err != nil {
		s.logger.Error(
			fmt.Sprintf("stream: error opening transaction log for writing: %v", err),
			"id", s.settings.GetRunID())
		return work
	}

	r, err := transactionlog.OpenReader(
		s.settings.GetTransactionLogPath(),
		s.logger,
	)
	if err != nil {
		// Capture the error because if we can open for writing,
		// why can't we open for reading?
		s.logger.CaptureError(
			fmt.Errorf("stream: error opening transaction log for reading: %v", err),
			"id", s.settings.GetRunID())
		return work
	}

	writer := s.writerFactory.New(w)
	flowControl := s.flowControlFactory.New(
		r, writer.Flush, s.recordParser,
		FlowControlParams{
			InMemorySize: 32,   // Max records before off-loading.
			Limit:        1024, // Max unsaved records before blocking.
		},
	)

	s.wg.Add(1)
	go func() {
		writer.Do(work)
		s.wg.Done()
	}()

	s.wg.Add(1)
	go func() {
		flowControl.Do(writer.Chan())
		s.wg.Done()
	}()

	return flowControl.Chan()
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
	s.HandleRecord(&spb.Record{
		RecordType: &spb.Record_Exit{
			Exit: &spb.RunExitRecord{
				ExitCode: exitCode,
			}},
		Control: &spb.Control{AlwaysSend: true},
	})

	s.Close()

	s.printFooter()
}

func (s *Stream) printFooter() {
	// Silent mode disables any footer output
	if s.settings.IsSilent() {
		return
	}

	formatter := pfxout.New(
		pfxout.WithColor("wandb", pfxout.BrightBlue),
	)

	formatter.Println("")
	if s.settings.IsOffline() {
		formatter.Println("You can sync this run to the cloud by running:")
		formatter.Println(
			pfxout.WithStyle(
				fmt.Sprintf("wandb sync %v", s.settings.GetSyncDir()),
				pfxout.Bold,
			),
		)
	} else if runURL, err := s.runURL(); err != nil {
		s.logger.CaptureError(fmt.Errorf("stream: runURL: %v", err))
	} else {
		formatter.Println(
			fmt.Sprintf(
				"🚀 View run %v at: %v",
				pfxout.WithColor(s.settings.GetDisplayName(), pfxout.Yellow),
				pfxout.WithColor(runURL, pfxout.Blue),
			),
		)
	}

	currentDir, err := os.Getwd()
	if err != nil {
		return
	}
	relLogDir, err := filepath.Rel(currentDir, s.settings.GetLogDir())
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

// runURL returns the URL for the run if available, or else an error.
func (s *Stream) runURL() (string, error) {
	upserter, err := s.runHandle.Upserter()
	if err != nil {
		return "", err
	}

	return upserter.RunPath().URL(s.settings.GetAppURL())
}
