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
	"github.com/wandb/wandb/core/pkg/observability"
)

// DefaultFileTransfer uploads or downloads files to/from the server
type DefaultFileTransfer struct {
	// client is the HTTP client for the file transfer
	client *retryablehttp.Client

	// logger is the logger for the file transfer
	logger *observability.CoreLogger

	// fileTransferStats is used to track upload/download progress
	fileTransferStats FileTransferStats
}

// NewDefaultFileTransfer creates a new fileTransfer
func NewDefaultFileTransfer(
	client *retryablehttp.Client,
	logger *observability.CoreLogger,
	fileTransferStats FileTransferStats,
) *DefaultFileTransfer {
	fileTransfer := &DefaultFileTransfer{
		logger:            logger,
		client:            client,
		fileTransferStats: fileTransferStats,
	}
	return fileTransfer
}

func (ft *DefaultFileTransfer) TransferType() FileTransferType {
	return FileTransferTypeDefault
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
	if err != nil {
		ft.logger.CaptureError("file transfer: upload: error getting file size", err, "path", task.Path)
		return err
	}

	// Don't try to upload directories.
	if stat.IsDir() {
		return fmt.Errorf(
			"file transfer: upload: cannot upload directory %v",
			task.Path,
		)
	}

	task.Size = stat.Size()

	progressReader, err := NewProgressReader(
		file,
		task.Size,
		func(processed int, total int) {
			if task.ProgressCallback != nil {
				task.ProgressCallback(processed, total)
			}

			ft.fileTransferStats.UpdateUploadStats(FileUploadInfo{
				FileKind:      task.FileKind,
				Path:          task.Path,
				UploadedBytes: int64(processed),
				TotalBytes:    int64(total),
			})
		},
	)
	if err != nil {
		return err
	}
	req, err := retryablehttp.NewRequest(http.MethodPut, task.Url, progressReader)
	if err != nil {
		return err
	}
	for _, header := range task.Headers {
		parts := strings.SplitN(header, ":", 2)
		if len(parts) != 2 {
			ft.logger.Error("file transfer: upload: invalid header", "header", header)
			continue
		}
		req.Header.Set(parts[0], parts[1])
	}
	if task.Context != nil {
		req = req.WithContext(task.Context)
	}
	resp, err := ft.client.Do(req)
	if err != nil {
		return err
	}
	if resp.StatusCode < 200 || resp.StatusCode > 299 {
		return fmt.Errorf("file transfer: upload: failed to upload: %s", resp.Status)
	}
	return nil
}

// Download downloads a file from the server
func (ft *DefaultFileTransfer) Download(task *Task) error {
	ft.logger.Debug("default file transfer: downloading file", "path", task.Path, "url", task.Url)
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

	// TODO: redo it to use the progress writer, to track the download progress
	resp, err := ft.client.Get(task.Url)
	if err != nil {
		return err
	}

	// open the file for writing and defer closing it
	file, err := os.Create(task.Path)
	if err != nil {
		return err
	}
	defer func(file *os.File) {
		if err := file.Close(); err != nil {
			ft.logger.CaptureError("file transfer: download: error closing file", err, "path", task.Path)
		}
	}(file)

	defer func(file io.ReadCloser) {
		if err := file.Close(); err != nil {
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
	// Note: this turns ProgressReader into a ReadSeeker, not just a Reader!
	// The retryablehttp client will seek to 0 on every retry.
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
