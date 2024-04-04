// Package filestream implements routines necessary for communicating with
// the W&B backend filestream service.
//
// Internally there are three goroutines spun up:
//
//	process:  process records into an appropriate format to transmit
//	transmit: collect and transmit messages to the filestream service
//	feedback: process feedback from the filestream service
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
//	 - loop_feedback.go: Filestream.add_feedback - add to feedback channel
//	{goroutine feedback}
//	 - loop_feedback.go: Filestream.loopFeedback - loop acting on feedback channel
//	{caller}
//	 - filestream.go:    FileStream.Close        - graceful shutdown of worker goroutines
package filestream

import (
	"sync"
	"time"

	"github.com/wandb/wandb/core/internal/api"
	"github.com/wandb/wandb/core/pkg/observability"
	"github.com/wandb/wandb/core/pkg/service"
)

const (
	BufferSize             = 32
	EventsFileName         = "wandb-events.jsonl"
	HistoryFileName        = "wandb-history.jsonl"
	SummaryFileName        = "wandb-summary.json"
	OutputFileName         = "output.log"
	defaultMaxItemsPerPush = 5_000
	defaultDelayProcess    = 20 * time.Millisecond
	defaultHeartbeatTime   = 2 * time.Second
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

// FileStream is a stream of data to the server
type FileStream struct {
	// The relative path on the server to which to make requests.
	//
	// This must not include the schema and hostname prefix.
	path string

	processChan  chan processTask
	transmitChan chan processedChunk
	feedbackChan chan map[string]interface{}

	processWait  *sync.WaitGroup
	transmitWait *sync.WaitGroup
	feedbackWait *sync.WaitGroup

	// keep track of where we are streaming each file chunk
	offsetMap FileStreamOffsetMap

	// settings is the settings for the filestream
	settings *service.Settings

	// logger is the logger for the filestream
	logger *observability.CoreLogger

	// The client for making API requests.
	apiClient api.Client

	maxItemsPerPush int
	delayProcess    time.Duration
	heartbeatTime   time.Duration

	clientId string
}

type FileStreamOption func(fs *FileStream)

func WithSettings(settings *service.Settings) FileStreamOption {
	return func(fs *FileStream) {
		fs.settings = settings
	}
}

func WithLogger(logger *observability.CoreLogger) FileStreamOption {
	return func(fs *FileStream) {
		fs.logger = logger
	}
}

func WithPath(path string) FileStreamOption {
	return func(fs *FileStream) {
		fs.path = path
	}
}

func WithAPIClient(client api.Client) FileStreamOption {
	return func(fs *FileStream) {
		fs.apiClient = client
	}
}

func WithMaxItemsPerPush(maxItemsPerPush int) FileStreamOption {
	return func(fs *FileStream) {
		fs.maxItemsPerPush = maxItemsPerPush
	}
}

func WithClientId(clientId string) FileStreamOption {
	// TODO: this should be the default behavior in the future
	return func(fs *FileStream) {
		if fs.settings.GetXShared().GetValue() {
			fs.clientId = clientId
		}
	}
}

func WithDelayProcess(delayProcess time.Duration) FileStreamOption {
	return func(fs *FileStream) {
		fs.delayProcess = delayProcess
	}
}

func WithHeartbeatTime(heartbeatTime time.Duration) FileStreamOption {
	return func(fs *FileStream) {
		fs.heartbeatTime = heartbeatTime
	}
}

func WithOffsets(offsetMap FileStreamOffsetMap) FileStreamOption {
	return func(fs *FileStream) {
		for k, v := range offsetMap {
			fs.offsetMap[k] = v
		}
	}
}

// func GetCheckRetryFunc() func(context.Context, *http.Response, error) (bool, error) {
// 	return func(ctx context.Context, resp *http.Response, err error) (bool, error) {
//      // Implement a custom retry function here
// 		return false, nil
//	}
// }

func NewFileStream(opts ...FileStreamOption) *FileStream {
	fs := &FileStream{
		processWait:     &sync.WaitGroup{},
		transmitWait:    &sync.WaitGroup{},
		feedbackWait:    &sync.WaitGroup{},
		processChan:     make(chan processTask, BufferSize),
		transmitChan:    make(chan processedChunk, BufferSize),
		feedbackChan:    make(chan map[string]interface{}, BufferSize),
		offsetMap:       make(FileStreamOffsetMap),
		maxItemsPerPush: defaultMaxItemsPerPush,
		delayProcess:    defaultDelayProcess,
		heartbeatTime:   defaultHeartbeatTime,
	}
	for _, opt := range opts {
		opt(fs)
	}
	return fs
}

// Start creates process, transmit, and feedback goroutines
func (fs *FileStream) Start() {
	fs.logger.Debug("filestream: start", "path", fs.path)

	fs.processWait.Add(1)
	go func() {
		fs.loopProcess(fs.processChan)
		fs.processWait.Done()
	}()

	fs.transmitWait.Add(1)
	go func() {
		fs.loopTransmit(fs.transmitChan)
		fs.transmitWait.Done()
	}()

	fs.feedbackWait.Add(1)
	go func() {
		fs.loopFeedback(fs.feedbackChan)
		fs.feedbackWait.Done()
	}()
}

// StreamRecord is the main entry point for callers to add data to be sent
func (fs *FileStream) StreamRecord(rec *service.Record) {
	if fs == nil {
		return
	}
	fs.logger.Debug("filestream: stream record", "record", rec)
	fs.addProcess(rec)
}

// Close gracefully shuts down the goroutines created by Start
func (fs *FileStream) Close() {
	if fs == nil {
		return
	}
	close(fs.processChan)
	fs.processWait.Wait()
	close(fs.transmitChan)
	fs.transmitWait.Wait()
	close(fs.feedbackChan)
	fs.feedbackWait.Wait()
	fs.logger.Debug("filestream: closed")
}
