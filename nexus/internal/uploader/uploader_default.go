package uploader

import (
	"fmt"
	"net/http"
	"os"
	"strings"

	"github.com/hashicorp/go-retryablehttp"
	"github.com/wandb/wandb/nexus/pkg/observability"
)

// DefaultUploader uploads files to the server
type DefaultUploader struct {
	// client is the HTTP client for the uploader
	client *retryablehttp.Client

	// logger is the logger for the uploader
	logger *observability.NexusLogger
}

// NewDefaultUploader creates a new uploader
func NewDefaultUploader(logger *observability.NexusLogger, client *retryablehttp.Client) *DefaultUploader {
	uploader := &DefaultUploader{
		logger: logger,
		client: client,
	}
	return uploader
}

// Upload uploads a file to the server
func (u *DefaultUploader) Upload(task *UploadTask) error {
	u.logger.Debug("default uploader: uploading file", "path", task.Path, "url", task.Url)
	// open the file for reading and defer closing it
	file, err := os.Open(task.Path)
	if err != nil {
		return err
	}
	defer func(file *os.File) {
		err := file.Close()
		if err != nil {
			u.logger.CaptureError("uploader: error closing file", err, "path", task.Path)
		}
	}(file)

	// req, err := retryablehttp.NewRequest(
	req, err := http.NewRequest(
		http.MethodPut,
		task.Url,
		file,
	)

	for _, header := range task.Headers {
		parts := strings.Split(header, ":")
		req.Header.Set(parts[0], parts[1])
	}

	if err != nil {
		return err
	}

	var resp *http.Response
	// if resp, err = u.client.Do(req); err != nil {
	if resp, err = http.DefaultClient.Do(req); err != nil {
		return err
	}
	fmt.Println(*resp)
	return nil
}
