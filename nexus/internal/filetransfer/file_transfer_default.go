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
func (ft *DefaultFileTransfer) Upload(task *Task) error {
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

	stat, err := file.Stat()
	if err == nil {
		task.Size = stat.Size()
	} else {
		ft.logger.CaptureError("file transfer: upload: error getting file size", err, "path", task.Path)
		return err
	}

	progressReader, err := NewProgressReader(file, task.Size, task.ProgressCallback)
	if err != nil {
		return err
	}
	req, err := retryablehttp.NewRequest(http.MethodPut, task.Url, progressReader)
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
func (ft *DefaultFileTransfer) Download(task *Task) error {
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

type ProgressReader struct {
	*os.File
	len              int
	read             int
	progressCallback func(processed, total int)
}

func NewProgressReader(file *os.File, size int64, progressCallback func(processed, total int)) (*ProgressReader, error) {
	if size > math.MaxInt {
		return &ProgressReader{}, fmt.Errorf("file larger than %v", math.MaxInt)
	}
	return &ProgressReader{
		File:             file,
		len:              int(size),
		progressCallback: progressCallback,
	}, nil
}

func (pr *ProgressReader) Read(p []byte) (int, error) {
	n, err := pr.File.Read(p)
	if err != nil {
		return n, err // Return early if there's an error
	}

	pr.read += n
	if pr.len > 0 {
		pr.progressCallback(pr.read, pr.len)
	}
	return n, err
}

func (pr *ProgressReader) Len() int {
	return pr.len
}
