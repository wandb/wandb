// Package filestream implements routines necessary for communicating with
// the W&B backend filestream service.
//
// Internally there are three goroutines spun up:
//
//	process:  process records into an appropriate format to transmit
//	transmit: collect and transmit messages to the filestream service
//
// Below demonstrates a common execution flow through this package:
//
//	{caller}:
//	 - filestream.go:    NewFileStream           - create service
//	 - filestream.go:    FileStream.Start        - spin up worker goroutines
//	 - filestream.go:    FileStream.StreamRecord - add a record to be processed and sent
//	 - loop_process.go:  Filestream.addProcess   - add to process channel
//	{goroutine process}:
//	 - loop_process.go:  Filestream.loopProcess  - loop acting on process channel
//	 - loop_transmit.go: Filestream.addTransmit  - add to transmit channel
//	{goroutine transmit}:
//	 - loop_transmit.go: Filestream.loopTransmit - loop acting on transmit channel
//	 - collector.go:     chunkCollector          - class to coordinate collecting work from transmit channel
//	 - collector.go:     chunkCollector.read     - read the first transmit work from transmit channel
//	 - collector.go:     chunkCollector.readMore - keep reading until we have enough or hit timeout
//	 - collector.go:     chunkCollector.dump     - create a blob to be used to serialize into json to send
//	 - loop_transmit.go: Filestream.send         - send json to backend filestream service
//	{caller}
//	 - filestream.go:    FileStream.Close        - graceful shutdown of worker goroutines
package filestream

import (
	"fmt"
	"sync"
	"time"

	"github.com/wandb/wandb/core/internal/api"
	"github.com/wandb/wandb/core/internal/waiting"
	"github.com/wandb/wandb/core/pkg/observability"
	"github.com/wandb/wandb/core/pkg/service"
)

const (
	BufferSize               = 32
	EventsFileName           = "wandb-events.jsonl"
	HistoryFileName          = "wandb-history.jsonl"
	SummaryFileName          = "wandb-summary.json"
	OutputFileName           = "output.log"
	defaultMaxItemsPerPush   = 5_000
	defaultDelayProcess      = 20 * time.Millisecond
	defaultHeartbeatInterval = 30 * time.Second
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

	// Close waits for all work to be completed.
	Close()

	// StreamRecord adds data to be sent to the filestream API.
	StreamRecord(rec *service.Record)

	// SignalFileUploaded tells the backend that a run file has been uploaded.
	//
	// This is used in some deployments where the backend is not notified when
	// files finish uploading.
	SignalFileUploaded(path string)

	// FatalErrorChan is a channel that emits if there is a fatal error.
	//
	// If this channel emits, all filestream operations afterward become
	// no-ops. This channel emits at most once, and it is never closed.
	FatalErrorChan() <-chan error
}

// fileStream is a stream of data to the server
type fileStream struct {
	// The relative path on the server to which to make requests.
	//
	// This must not include the schema and hostname prefix.
	path string

	transmitChan chan processedChunk
	transmitWait *sync.WaitGroup

	// keep track of where we are streaming each file chunk
	offsetMap FileStreamOffsetMap

	// settings is the settings for the filestream
	settings *service.Settings

	// logger is the logger for the filestream
	logger *observability.CoreLogger

	// The client for making API requests.
	apiClient api.Client

	maxItemsPerPush int
	delayProcess    waiting.Delay

	// A schedule on which to send heartbeats to the backend
	// to prove the run is still alive.
	heartbeatStopwatch waiting.Stopwatch

	clientId string

	// A channel that is closed if there is a fatal error.
	deadChan       chan struct{}
	deadChanOnce   *sync.Once
	fatalErrorChan chan error
}

type FileStreamParams struct {
	Settings           *service.Settings
	Logger             *observability.CoreLogger
	ApiClient          api.Client
	MaxItemsPerPush    int
	ClientId           string
	DelayProcess       waiting.Delay
	HeartbeatStopwatch waiting.Stopwatch
}

func NewFileStream(params FileStreamParams) FileStream {
	fs := &fileStream{
		settings:        params.Settings,
		logger:          params.Logger,
		apiClient:       params.ApiClient,
		transmitWait:    &sync.WaitGroup{},
		transmitChan:    make(chan processedChunk, BufferSize),
		offsetMap:       make(FileStreamOffsetMap),
		maxItemsPerPush: defaultMaxItemsPerPush,
		deadChanOnce:    &sync.Once{},
		deadChan:        make(chan struct{}),
		fatalErrorChan:  make(chan error, 1),
	}

	fs.delayProcess = params.DelayProcess
	if fs.delayProcess == nil {
		fs.delayProcess = waiting.NewDelay(defaultDelayProcess)
	}

	fs.heartbeatStopwatch = params.HeartbeatStopwatch
	if fs.heartbeatStopwatch == nil {
		fs.heartbeatStopwatch = waiting.NewStopwatch(defaultHeartbeatInterval)
	}

	if params.MaxItemsPerPush > 0 {
		fs.maxItemsPerPush = params.MaxItemsPerPush
	}

	// TODO: this should become the default
	if fs.settings.GetXShared().GetValue() && params.ClientId != "" {
		fs.clientId = params.ClientId
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

	for k, v := range offsetMap {
		fs.offsetMap[k] = v
	}

	fs.transmitWait.Add(1)
	go func() {
		defer func() {
			fs.transmitWait.Done()
			fs.recoverUnexpectedPanic()
		}()

		fs.loopTransmit(fs.transmitChan)
	}()
}

func (fs *fileStream) StreamRecord(rec *service.Record) {
	fs.logger.Debug("filestream: stream record", "record", rec)
	fs.addProcess(processTask{Record: rec})
}

func (fs *fileStream) SignalFileUploaded(path string) {
	fs.addProcess(processTask{UploadedFile: path})
}

func (fs *fileStream) FatalErrorChan() <-chan error {
	return fs.fatalErrorChan
}

func (fs *fileStream) Close() {
	close(fs.transmitChan)
	fs.transmitWait.Wait()
	fs.logger.Debug("filestream: closed")
}

// logFatalAndStopWorking logs a fatal error and kills the filestream.
//
// After this, most filestream operations are no-ops. This is meant for
// when we can't guarantee correctness, in which case we stop uploading
// data but continue to save it to disk to avoid data loss.
func (fs *fileStream) logFatalAndStopWorking(err error) {
	fs.logger.CaptureFatal("filestream: fatal error", err)
	fs.deadChanOnce.Do(func() {
		close(fs.deadChan)
		fs.fatalErrorChan <- err
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

// recoverUnexpectedPanic redirects panics to FatalErrorChan.
//
// This should be used in a `defer` statement at the top of a function. This
// is intended for truly *unexpected* panics to completely panic-proof critical
// goroutines. All other errors should directly use `pushFatalError`.
func (fs *fileStream) recoverUnexpectedPanic() {
	if e := recover(); e != nil {
		fs.logFatalAndStopWorking(
			fmt.Errorf("filestream: unexpected panic: %v", e),
		)
	}
}
