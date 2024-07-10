// Package filestream communicates with the W&B backend filestream service.
package filestream

import (
	"fmt"
	"sync"
	"time"

	"github.com/wandb/wandb/core/internal/api"
	"github.com/wandb/wandb/core/internal/settings"
	"github.com/wandb/wandb/core/internal/waiting"
	"github.com/wandb/wandb/core/pkg/observability"
	"golang.org/x/time/rate"
)

const (
	BufferSize               = 32
	EventsFileName           = "wandb-events.jsonl"
	HistoryFileName          = "wandb-history.jsonl"
	SummaryFileName          = "wandb-summary.json"
	OutputFileName           = "output.log"
	defaultHeartbeatInterval = 30 * time.Second

	// Maximum line length for filestream jsonl files, imposed by the back-end.
	//
	// See https://github.com/wandb/core/pull/7339 for history.
	maxFileLineBytes = (10 << 20) - (100 << 10)
)

type ChunkTypeEnum int8
type FileStreamOffsetMap map[ChunkTypeEnum]int

const (
	NoneChunk ChunkTypeEnum = iota
	HistoryChunk
	OutputChunk
	EventsChunk
	SummaryChunk
)

type FileStream interface {
	// Start asynchronously begins to upload to the backend.
	//
	// All operations are associated with the specified run (defined by
	// `entity`, `project` and `runID`). In case we are resuming a run,
	// the `offsetMap` specifies the initial file offsets for each file
	// type (history, output logs, events, summary).
	Start(
		entity string,
		project string,
		runID string,
		offsetMap FileStreamOffsetMap,
	)

	// FinishWithExit marks the run as complete and blocks until all
	// uploads finish.
	FinishWithExit(exitCode int32)

	// FinishWithoutExit blocks until all uploads finish but does not
	// mark the run as complete.
	FinishWithoutExit()

	// StreamUpdate uploads information through the filestream API.
	StreamUpdate(update Update)
}

// fileStream is a stream of data to the server
type fileStream struct {
	// The relative path on the server to which to make requests.
	//
	// This must not include the schema and hostname prefix.
	path string

	processChan  chan Update
	feedbackWait *sync.WaitGroup

	// settings is the settings for the filestream
	settings *settings.Settings

	// A logger for internal debug logging.
	logger *observability.CoreLogger

	// A way to print console messages to the user.
	printer *observability.Printer

	// The client for making API requests.
	apiClient api.Client

	// The rate limit for sending data to the backend.
	transmitRateLimit *rate.Limiter

	// A schedule on which to send heartbeats to the backend
	// to prove the run is still alive.
	heartbeatStopwatch waiting.Stopwatch

	// A channel that is closed if there is a fatal error.
	deadChan     chan struct{}
	deadChanOnce *sync.Once
}

type FileStreamParams struct {
	Settings           *settings.Settings
	Logger             *observability.CoreLogger
	Printer            *observability.Printer
	ApiClient          api.Client
	TransmitRateLimit  *rate.Limiter
	HeartbeatStopwatch waiting.Stopwatch
}

func NewFileStream(params FileStreamParams) FileStream {
	// Panic early to avoid surprises. These fields are required.
	switch {
	case params.Logger == nil:
		panic("filestream: nil logger")
	case params.Printer == nil:
		panic("filestream: nil printer")
	case params.TransmitRateLimit == nil:
		panic("filestream: nil rate limit")
	}

	fs := &fileStream{
		settings:          params.Settings,
		logger:            params.Logger,
		printer:           params.Printer,
		apiClient:         params.ApiClient,
		processChan:       make(chan Update, BufferSize),
		feedbackWait:      &sync.WaitGroup{},
		transmitRateLimit: params.TransmitRateLimit,
		deadChanOnce:      &sync.Once{},
		deadChan:          make(chan struct{}),
	}

	fs.heartbeatStopwatch = params.HeartbeatStopwatch
	if fs.heartbeatStopwatch == nil {
		fs.heartbeatStopwatch = waiting.NewStopwatch(defaultHeartbeatInterval)
	}

	return fs
}

func (fs *fileStream) Start(
	entity string,
	project string,
	runID string,
	offsetMap FileStreamOffsetMap,
) {
	fs.logger.Debug("filestream: start", "path", fs.path)

	fs.path = fmt.Sprintf(
		"files/%s/%s/%s/file_stream",
		entity,
		project,
		runID,
	)

	transmitChan := fs.startProcessingUpdates(fs.processChan)
	feedbackChan := fs.startTransmitting(transmitChan, offsetMap)
	fs.startProcessingFeedback(feedbackChan, fs.feedbackWait)
}

func (fs *fileStream) StreamUpdate(update Update) {
	fs.logger.Debug("filestream: stream update", "update", update)
	select {
	case fs.processChan <- update:
	case <-fs.deadChan:
		// Ignore everything if the filestream is dead.
	}
}

func (fs *fileStream) FinishWithExit(exitCode int32) {
	fs.StreamUpdate(&ExitUpdate{ExitCode: exitCode})
	fs.FinishWithoutExit()
}

func (fs *fileStream) FinishWithoutExit() {
	close(fs.processChan)
	fs.feedbackWait.Wait()
	fs.logger.Debug("filestream: closed")
}

// logFatalAndStopWorking logs a fatal error and kills the filestream.
//
// After this, most filestream operations are no-ops. This is meant for
// when we can't guarantee correctness, in which case we stop uploading
// data but continue to save it to disk to avoid data loss.
func (fs *fileStream) logFatalAndStopWorking(err error) {
	fs.logger.CaptureFatal(fmt.Errorf("filestream: fatal error: %v", err))
	fs.deadChanOnce.Do(func() {
		close(fs.deadChan)
		fs.printer.Write(
			"Fatal error while uploading data. Some run data will" +
				" not be synced, but it will still be written to disk. Use" +
				" `wandb sync` at the end of the run to try uploading.",
		)
	})
}

// isDead reports whether the filestream has been killed.
func (fs *fileStream) isDead() bool {
	select {
	case <-fs.deadChan:
		return true
	default:
		return false
	}
}
