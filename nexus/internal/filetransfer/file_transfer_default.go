package filetransfer

import (
	"fmt"
	"io"
	"math"
	"net/http"
	"os"
	"strings"

	"github.com/hashicorp/go-retryablehttp"
	"github.com/wandb/wandb/nexus/pkg/observability"
)

// DefaultFileTransfer uploads or downloads files to/from the server
type DefaultFileTransfer struct {
	// client is the HTTP client for the file transfer
	client *retryablehttp.Client

	// logger is the logger for the file transfer
	logger *observability.NexusLogger
}

// NewDefaultFileTransfer creates a new fileTransfer
func NewDefaultFileTransfer(logger *observability.NexusLogger, client *retryablehttp.Client) *DefaultFileTransfer {
	fileTransfer := &DefaultFileTransfer{
		logger: logger,
		client: client,
	}
	return fileTransfer
}

// Upload uploads a file to the server
func (ft *DefaultFileTransfer) Upload(task *UploadTask) error {
	ft.logger.Debug("default file transfer: uploading file", "path", task.Path, "url", task.Url)

	// open the file for reading and defer closing it
	file, err := os.Open(task.Path)
	if err != nil {
		return err
	}
	defer func(file *os.File) {
		err := file.Close()
		if err != nil {
			ft.logger.CaptureError("file transfer: upload: error closing file", err, "path", task.Path)
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

	if _, err = ft.client.Do(req); err != nil {
		return err
	}

	return nil
}

// Download downloads a file from the server
func (ft *DefaultFileTransfer) Download(task *DownloadTask) error {
	ft.logger.Debug("default file transfer: downloading file", "path", task.Path, "url", task.Url)
	// open the file for writing and defer closing it
	file, err := os.Create(task.Path)
	if err != nil {
		return err
	}
	defer func(file *os.File) {
		err := file.Close()
		if err != nil {
			ft.logger.CaptureError("file transfer: download: error closing file", err, "path", task.Path)
		}
	}(file)

	resp, err := ft.client.Get(task.Url)
	if err != nil {
		return err
	}
	defer func(file io.ReadCloser) {
		err := file.Close()
		if err != nil {
			ft.logger.CaptureError("file transfer: download: error closing response reader", err, "path", task.Path)
		}
	}(resp.Body)
	_, err = io.Copy(file, resp.Body)
	if err != nil {
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
