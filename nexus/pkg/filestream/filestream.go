// package filesteam implements routines necessary for communicating with
// the W&B backend filestream service.
//
// Internally there are three goroutines spun up:
//
//	process:  process records into an appopriate format to transmit
//	transmit: transmit messages to the filestream service
//	feedback: process feedback from the filestream service
package filestream

import (
	"sync"
	"time"

	"github.com/hashicorp/go-retryablehttp"

	"github.com/wandb/wandb/nexus/pkg/observability"
	"github.com/wandb/wandb/nexus/pkg/service"
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
	path string

	processChan  chan *service.Record
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
	logger *observability.NexusLogger

	// httpClient is the http client
	httpClient *retryablehttp.Client

	maxItemsPerPush int
	delayProcess    time.Duration
	heartbeatTime   time.Duration
}

type FileStreamOption func(fs *FileStream)

func WithSettings(settings *service.Settings) FileStreamOption {
	return func(fs *FileStream) {
		fs.settings = settings
	}
}

func WithLogger(logger *observability.NexusLogger) FileStreamOption {
	return func(fs *FileStream) {
		fs.logger = logger
	}
}

func WithPath(path string) FileStreamOption {
	return func(fs *FileStream) {
		fs.path = path
	}
}

func WithHttpClient(client *retryablehttp.Client) FileStreamOption {
	return func(fs *FileStream) {
		fs.httpClient = client
	}
}

func WithMaxItemsPerPush(maxItemsPerPush int) FileStreamOption {
	return func(fs *FileStream) {
		fs.maxItemsPerPush = maxItemsPerPush
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
		processChan:     make(chan *service.Record, BufferSize),
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

func (fs *FileStream) StreamRecord(rec *service.Record) {
	fs.logger.Debug("filestream: stream record", "record", rec)
	fs.addProcess(rec)
}

func (fs *FileStream) Close() {
	close(fs.processChan)
	fs.processWait.Wait()
	close(fs.transmitChan)
	fs.transmitWait.Wait()
	close(fs.feedbackChan)
	fs.feedbackWait.Wait()
	fs.logger.Debug("filestream: closed")
}
