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

type FileWithLen struct {
	*os.File
}

func (f *FileWithLen) Len() int {
	fileInfo, err := f.Stat()
	if err != nil {
		return 0
	}
	return int(fileInfo.Size())
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

	fileInfo := FileWithLen{
		file,
	}
	req, err := retryablehttp.NewRequest(
		http.MethodPut,
		task.Url,
		&fileInfo,
	)

	for _, header := range task.Headers {
		parts := strings.Split(header, ":")
		req.Header.Set(parts[0], parts[1])
	}

	if err != nil {
		return err
	}

	resp, err := u.client.Do(req)
	if err != nil {
		return err
	} else if resp.StatusCode != 200 {
		return fmt.Errorf(resp.Status)
	}
	return nil
}
