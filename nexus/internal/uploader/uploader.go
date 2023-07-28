package uploader

import (
	"context"
	"net/http"
	"os"
	"strings"
	"sync"
	"time"

	"golang.org/x/exp/slog"

	"github.com/wandb/wandb/nexus/pkg/observability"

	"github.com/hashicorp/go-retryablehttp"
)

const UploaderBufferSize = 32

// UploadTask is a task to upload a file
type UploadTask struct {

	// path is the path to the file
	Path string

	// url is the endpoint to upload to
	Url string

	// headers to send on the upload
	Headers []string

	// allow tasks to wait for completion (failed or success)
	WgOutstanding *sync.WaitGroup
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

func (t *UploadTask) outstandingAdd() {
	if t.WgOutstanding == nil {
		return
	}
	t.WgOutstanding.Add(1)
}

func (t *UploadTask) outstandingDone() {
	if t.WgOutstanding == nil {
		return
	}
	t.WgOutstanding.Done()
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
		inChan:      make(chan *UploadTask, UploaderBufferSize),
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
				u.logger.CaptureError("uploader: error uploading", err, "path", task.Path, "url", task.Url)
			}
		}
		u.wg.Done()
	}()
}

// AddTask adds a task to the uploader
func (u *Uploader) AddTask(task *UploadTask) {
	task.outstandingAdd()
	u.logger.Debug("uploader: adding task", "path", task.Path, "url", task.Url)
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
	// read in the file at task.Path:
	file, err := os.ReadFile(task.Path)
	if err != nil {
		return err
	}

	req, err := retryablehttp.NewRequest(
		http.MethodPut,
		task.Url,
		file,
	)

	for _, header := range task.Headers {
		parts := strings.Split(header, ":")
		req.Header.Set(parts[0], parts[1])
	}

	if err != nil {
		task.outstandingDone()
		return err
	}

	if _, err = u.retryClient.Do(req); err != nil {
		task.outstandingDone()
		return err
	}
	task.outstandingDone()
	return nil
}
