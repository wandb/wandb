package uploader

import (
	"fmt"
	"math"
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

	fileWithLen, err := NewFileWithLen(file)
	if err != nil {
		return err
	}
	req, err := retryablehttp.NewRequest(http.MethodPut, task.Url, fileWithLen)
	if err != nil {
		return err
	}
	for _, header := range task.Headers {
		parts := strings.Split(header, ":")
		req.Header.Set(parts[0], parts[1])
	}

	if _, err = u.client.Do(req); err != nil {
		return err
	}

	return nil
}

type FileWithLen struct {
	*os.File
	len int
}

func NewFileWithLen(file *os.File) (FileWithLen, error) {
	stat, err := file.Stat()
	if err != nil {
		return FileWithLen{}, err
	}
	if stat.Size() > math.MaxInt {
		return FileWithLen{}, fmt.Errorf("file larger than %v", math.MaxInt)
	}
	return FileWithLen{file, int(stat.Size())}, nil
}

func (f FileWithLen) Len() int {
	return f.len
}
