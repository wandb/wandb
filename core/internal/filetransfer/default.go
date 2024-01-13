package filetransfer

import (
	"fmt"
	"io"
	"math"
	"net/http"
	"os"
	"path"
	"strings"

	"github.com/hashicorp/go-retryablehttp"

	obs "github.com/wandb/wandb/core/internal/observability"
)

// DefaultTransferer uploads or downloads files to/from the server
type DefaultTransferer struct {
	// Client is the HTTP Client for the file transfer
	Client *retryablehttp.Client

	// Logger is the Logger for the file transfer
	Logger *obs.CoreLogger
}

// NewDefaultTransferer creates a new fileTransfer
func NewDefaultTransferer(logger *obs.CoreLogger, client *retryablehttp.Client) *DefaultTransferer {
	fileTransfer := &DefaultTransferer{
		Logger: logger,
		Client: client,
	}
	return fileTransfer
}

// Upload uploads a file to the server
func (ft *DefaultTransferer) Upload(task *Task) error {
	ft.Logger.Debug("default file transfer: uploading file", "path", task.Path, "url", task.Url)

	// open the file for reading and defer closing it
	file, err := os.Open(task.Path)
	if err != nil {
		return err
	}
	defer func(file *os.File) {
		err := file.Close()
		if err != nil {
			ft.Logger.CaptureError("file transfer: upload: error closing file", err, "path", task.Path)
		}
	}(file)

	stat, err := file.Stat()
	if err != nil {
		ft.Logger.CaptureError("file transfer: upload: error getting file size", err, "path", task.Path)
		return err
	}
	task.Size = stat.Size()

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

	if _, err = ft.Client.Do(req); err != nil {
		return err
	}

	return nil
}

// Download downloads a file from the server
func (ft *DefaultTransferer) Download(task *Task) error {
	ft.Logger.Debug("default file transfer: downloading file", "path", task.Path, "url", task.Url)
	dir := path.Dir(task.Path)

	// Check if the directory already exists
	if _, err := os.Stat(dir); os.IsNotExist(err) {
		// Directory doesn't exist, create it
		if err := os.MkdirAll(dir, os.ModePerm); err != nil {
			// Handle the error if it occurs
			return err
		}
	} else if err != nil {
		// Handle other errors that may occur while checking directory existence
		return err
	}

	// open the file for writing and defer closing it
	file, err := os.Create(task.Path)
	if err != nil {
		return err
	}
	defer func(file *os.File) {
		err := file.Close()
		if err != nil {
			ft.Logger.CaptureError("file transfer: download: error closing file", err, "path", task.Path)
		}
	}(file)

	resp, err := ft.Client.Get(task.Url)
	if err != nil {
		return err
	}
	defer func(file io.ReadCloser) {
		err := file.Close()
		if err != nil {
			ft.Logger.CaptureError("file transfer: download: error closing response reader", err, "path", task.Path)
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
	len      int
	read     int
	callback func(processed, total int)
}

func NewProgressReader(file *os.File, size int64, callback func(processed, total int)) (*ProgressReader, error) {
	if size > math.MaxInt {
		return &ProgressReader{}, fmt.Errorf("file larger than %v", math.MaxInt)
	}
	return &ProgressReader{
		File:     file,
		len:      int(size),
		callback: callback,
	}, nil
}

func (pr *ProgressReader) Read(p []byte) (int, error) {
	n, err := pr.File.Read(p)
	if err != nil {
		return n, err // Return early if there's an error
	}

	pr.read += n
	if pr.callback != nil {
		pr.callback(pr.read, pr.len)
	}
	return n, err
}

func (pr *ProgressReader) Len() int {
	return pr.len
}
