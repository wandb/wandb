package server

import (
	"context"
	"net/http"
	"os"
	"sync"
	"time"

	"golang.org/x/exp/slog"

	"github.com/wandb/wandb/nexus/pkg/observability"

	"github.com/hashicorp/go-retryablehttp"
)

// UploadTask is a task to upload a file
type UploadTask struct {

	// path is the path to the file
	path string

	// url is the endpoint to upload to
	url string
}

type fileCounts struct {
	// wandbCount    int
	// mediaCount    int
	// artifactCount int
	// otherCount    int
}

// Uploader uploads files to the server
type Uploader struct {
	// ctx is the context for the uploader
	ctx context.Context

	// inChan is the channel for incoming messages
	inChan chan *UploadTask

	// retryClient is the retryable http client
	retryClient *retryablehttp.Client

	// fileCounts is the file counts
	fileCounts fileCounts

	// logger is the logger for the uploader
	logger *observability.NexusLogger

	// wg is the wait group
	wg *sync.WaitGroup
}

// NewUploader creates a new uploader
func NewUploader(ctx context.Context, logger *observability.NexusLogger) *Uploader {
	retryClient := retryablehttp.NewClient()
	retryClient.Logger = slog.NewLogLogger(logger.Logger.Handler(), slog.LevelDebug)
	retryClient.RetryMax = 10
	retryClient.RetryWaitMin = 1 * time.Second
	retryClient.RetryWaitMax = 60 * time.Second

	uploader := &Uploader{
		ctx:         ctx,
		inChan:      make(chan *UploadTask, BufferSize),
		retryClient: retryClient,
		fileCounts:  fileCounts{},
		logger:      logger,
		wg:          &sync.WaitGroup{},
	}
	uploader.do()
	return uploader
}

// do is the main loop for the uploader
func (u *Uploader) do() {

	u.wg.Add(1)
	go func() {
		for task := range u.inChan {
			u.logger.Debug("uploader: got task", task)
			if err := u.upload(task); err != nil {
				u.logger.CaptureError("uploader: error uploading", err, "path", task.path, "url", task.url)
			}
		}
		u.wg.Done()
	}()
}

// AddTask adds a task to the uploader
func (u *Uploader) AddTask(task *UploadTask) {
	u.logger.Debug("uploader: adding task", "path", task.path, "url", task.url)
	u.inChan <- task
}

// Close closes the uploader
func (u *Uploader) Close() {
	u.logger.Debug("uploader: Close")
	close(u.inChan)
	u.wg.Wait()
}

// upload uploads a file to the server
func (u *Uploader) upload(task *UploadTask) error {
	// read in the file at task.path:
	file, err := os.ReadFile(task.path)
	if err != nil {
		return err
	}

	req, err := retryablehttp.NewRequest(
		http.MethodPut,
		task.url,
		file,
	)
	if err != nil {
		return err
	}

	if _, err = u.retryClient.Do(req); err != nil {
		return err
	}
	return nil
}
