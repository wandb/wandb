package uploader

import (
	"log/slog"
	"net/http"
	"os"
	"strings"
	"time"

	"github.com/hashicorp/go-retryablehttp"
	"github.com/wandb/wandb/nexus/pkg/observability"
)

type RetryClientOption func(rc *retryablehttp.Client)

func WithRetryClientLogger(logger *observability.NexusLogger) RetryClientOption {
	return func(rc *retryablehttp.Client) {
		rc.Logger = slog.NewLogLogger(logger.Logger.Handler(), slog.LevelDebug)
	}
}

func WithRetryClientRetryMax(retryMax int) RetryClientOption {
	return func(rc *retryablehttp.Client) {
		rc.RetryMax = retryMax
	}
}

func WithRetryClientRetryWaitMin(retryWaitMin time.Duration) RetryClientOption {
	return func(rc *retryablehttp.Client) {
		rc.RetryWaitMin = retryWaitMin
	}
}

func WithRetryClientRetryWaitMax(retryWaitMax time.Duration) RetryClientOption {
	return func(rc *retryablehttp.Client) {
		rc.RetryWaitMax = retryWaitMax
	}
}

func NewRetryClient(opts ...RetryClientOption) *retryablehttp.Client {
	retryClient := retryablehttp.NewClient()

	for _, opt := range opts {
		opt(retryClient)
	}
	return retryClient
}

// DefaultUploader uploads files to the server
type DefaultUploader struct {
	// client is the HTTP client for the uploader
	client *retryablehttp.Client

	// logger is the logger for the uploader
	logger *observability.NexusLogger
}

// NewDefaultUploader creates a new uploader
func NewDefaultUploader(logger *observability.NexusLogger) *DefaultUploader {
	retryClient := NewRetryClient(
		WithRetryClientLogger(logger),
		WithRetryClientRetryMax(10),                 // todo: make this configurable
		WithRetryClientRetryWaitMin(1*time.Second),  // todo: make this configurable
		WithRetryClientRetryWaitMax(60*time.Second), // todo: make this configurable
	)

	uploader := &DefaultUploader{
		client: retryClient,
		logger: logger,
	}
	return uploader
}

// Upload uploads a file to the server
func (u *DefaultUploader) Upload(task *UploadTask) error {
	u.logger.Debug("custom uploader: uploading file", "path", task.Path, "url", task.Url)
	// open the file for reading and defer closing it
	file, err := os.Open(task.Path)
	if err != nil {
		task.outstandingDone()
		return err
	}
	defer func(file *os.File) {
		err := file.Close()
		if err != nil {
			u.logger.CaptureError("uploader: error closing file", err, "path", task.Path)
		}
	}(file)

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

	if _, err = u.client.Do(req); err != nil {
		task.outstandingDone()
		return err
	}

	task.outstandingDone()
	return nil
}
