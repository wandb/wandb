// Package filestream communicates with the W&B backend filestream service.
package filestream

import (
	"fmt"
	"sync"
	"time"

	"github.com/google/wire"
	"github.com/wandb/wandb/core/internal/api"
	"github.com/wandb/wandb/core/internal/observability"
	"github.com/wandb/wandb/core/internal/settings"
	"github.com/wandb/wandb/core/internal/waiting"
	"github.com/wandb/wandb/core/internal/wboperation"
	"golang.org/x/time/rate"
)

const (
	BufferSize               = 32
	EventsFileName           = "wandb-events.jsonl"
	HistoryFileName          = "wandb-history.jsonl"
	SummaryFileName          = "wandb-summary.json"
	OutputFileName           = "output.log"
	defaultHeartbeatInterval = 30 * time.Second
	defaultTransmitInterval  = 15 * time.Second

	// Maximum line length for filestream jsonl files, imposed by the back-end.
	//
	// See https://github.com/wandb/core/pull/7339 for history.
	defaultMaxFileLineBytes = (10 << 20) - (100 << 10)

	// Retry filestream requests for 7 days before dropping chunk
	// retry_count = seconds_in_7_days / max_retry_time + num_retries_until_max_60_sec
	//             = 7 * 86400 / 60 + ceil(log2(60/2))
	//             = 10080 + 5
	DefaultRetryMax     = 10085
	DefaultRetryWaitMin = 2 * time.Second
	DefaultRetryWaitMax = 60 * time.Second
	// A 3-minute timeout for all filestream post requests
	DefaultNonRetryTimeout = 180 * time.Second
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

	mu         sync.Mutex
	isFinished bool

	processChan  chan Update
	feedbackWait *sync.WaitGroup

	// settings is the settings for the filestream
	settings *settings.Settings

	// A logger for internal debug logging.
	logger *observability.CoreLogger

	// The context in which to track filestream operations.
	operations *wboperation.WandbOperations

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

// FileStreamProviders binds FileStreamFactory.
var FileStreamProviders = wire.NewSet(
	wire.Struct(new(FileStreamFactory), "*"),
)

type FileStreamFactory struct {
	Logger     *observability.CoreLogger
	Operations *wboperation.WandbOperations
	Printer    *observability.Printer
	Settings   *settings.Settings
}

// New returns a new FileStream.
func (f *FileStreamFactory) New(
	apiClient api.Client,
	heartbeatStopwatch waiting.Stopwatch,
	transmitRateLimit *rate.Limiter,
) FileStream {
	// Panic early to avoid surprises. These fields are required.
	switch {
	case f.Logger == nil:
		panic("filestream: nil logger")
	case f.Printer == nil:
		panic("filestream: nil printer")
	}

	fs := &fileStream{
		settings:     f.Settings,
		logger:       f.Logger,
		operations:   f.Operations,
		printer:      f.Printer,
		apiClient:    apiClient,
		processChan:  make(chan Update, BufferSize),
		feedbackWait: &sync.WaitGroup{},
		deadChanOnce: &sync.Once{},
		deadChan:     make(chan struct{}),
	}

	fs.heartbeatStopwatch = heartbeatStopwatch
	if fs.heartbeatStopwatch == nil {
		fs.heartbeatStopwatch = waiting.NewStopwatch(defaultHeartbeatInterval)
	}

	fs.transmitRateLimit = transmitRateLimit
	if fs.transmitRateLimit == nil {
		fs.transmitRateLimit = rate.NewLimiter(rate.Every(defaultTransmitInterval), 1)
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

	fs.mu.Lock()
	defer fs.mu.Unlock()

	if fs.isFinished {
		fs.logger.CaptureError(fmt.Errorf("filestream: StreamUpdate after Finish"))
		return
	}

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
	fs.mu.Lock()
	if fs.isFinished {
		return
	}
	fs.isFinished = true
	fs.mu.Unlock()

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
