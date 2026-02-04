package filetransfer

import (
	"errors"
	"fmt"
	"io"
	"math"
	"net/http"
	"os"
	"path"
	"strings"

	"github.com/hashicorp/go-retryablehttp"

	"github.com/wandb/wandb/core/internal/api"
	"github.com/wandb/wandb/core/internal/observability"
	"github.com/wandb/wandb/core/internal/wboperation"
)

// DefaultFileTransfer uploads or downloads files to/from the server
type DefaultFileTransfer struct {
	// client is the HTTP client for the file transfer
	client api.RetryableClient

	// logger is the logger for the file transfer
	logger *observability.CoreLogger

	// fileTransferStats is used to track upload/download progress
	fileTransferStats FileTransferStats
}

// NewDefaultFileTransfer creates a new fileTransfer
func NewDefaultFileTransfer(
	client api.RetryableClient,
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

// Upload implements FileTransfer.Upload
func (ft *DefaultFileTransfer) Upload(task *DefaultUploadTask) error {
	ft.logger.Debug(
		"default file transfer: uploading file",
		"path", task.Path,
		"url", task.Url,
	)

	// open the file for reading and defer closing it
	file, err := os.Open(task.Path)
	if err != nil {
		return err
	}
	defer func(file *os.File) {
		err := file.Close()
		if err != nil {
			ft.logger.CaptureError(
				fmt.Errorf(
					"file transfer: upload: error closing file %s: %v",
					task.Path,
					err,
				))
		}
	}(file)

	requestBody, err := getUploadRequestBody(task, file, ft.fileTransferStats, ft.logger)
	if err != nil {
		return err
	}

	req, err := retryablehttp.NewRequest(http.MethodPut, task.Url, requestBody)
	if err != nil {
		return err
	}
	for _, header := range task.Headers {
		parts := strings.SplitN(header, ":", 2)
		if len(parts) != 2 {
			ft.logger.Error(
				"file transfer: upload: invalid header",
				"header", header,
			)
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
		// Try to read the body to know the detail error message
		return attachErrorResponseBody(
			"file transfer: upload: failed to upload: status: "+resp.Status,
			resp,
		)
	}
	task.Response = resp

	return nil
}

// attachErrorResponseBody returns an error with the error prefix and
// the first 1024 bytes of the response body. It closes the response
// body after reading the first 1024 bytes.
func attachErrorResponseBody(errPrefix string, resp *http.Response) error {
	// Only read first 1024 bytes of error message
	body, err := io.ReadAll(io.LimitReader(resp.Body, 1024))
	resp.Body.Close()
	if err != nil {
		return fmt.Errorf("%s: error reading body: %s", errPrefix, err)
	}
	return fmt.Errorf("%s: body: %s", errPrefix, string(body))
}

// Download implements FileTransfer.Download
func (ft *DefaultFileTransfer) Download(task *DefaultDownloadTask) error {
	ft.logger.Debug(
		"default file transfer: downloading file",
		"path", task.Path,
		"url", task.Url,
	)
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

	req, err := retryablehttp.NewRequest(http.MethodGet, task.Url, nil)
	if err != nil {
		return err
	}
	resp, err := ft.client.Do(req)
	if err != nil {
		return err
	}
	task.Response = resp

	// open the file for writing and defer closing it
	file, err := os.Create(task.Path)
	if err != nil {
		return err
	}
	defer func(file *os.File) {
		if err := file.Close(); err != nil {
			ft.logger.CaptureError(
				fmt.Errorf(
					"file transfer: download: error closing file %s: %v",
					task.Path,
					err,
				))
		}
	}(file)

	defer func(file io.ReadCloser) {
		if err := file.Close(); err != nil {
			ft.logger.CaptureError(
				fmt.Errorf(
					"file transfer: download: error closing response reader: %v",
					err,
				))
		}
	}(resp.Body)

	progress, err := wboperation.Get(task.Context).NewProgress()
	if err != nil {
		ft.logger.CaptureError(fmt.Errorf("file transfer: download: %v", err))
	}

	// If Size is not set, try to get it from Content-Length header
	size := task.Size
	if size == 0 && resp.ContentLength > 0 {
		size = resp.ContentLength
	}

	progressWriter := NewProgressWriter(
		file,
		func(processed int64) {
			if task.ProgressCallback != nil {
				task.ProgressCallback(int(processed), int(size))
			}

			if size == 0 {
				progress.SetBytesDone(int(processed))
			} else {
				progress.SetBytesOfTotal(int(processed), int(size))
			}
		},
	)
	_, err = io.Copy(progressWriter, resp.Body)
	if err != nil && !errors.Is(err, io.EOF) {
		return err
	}
	return nil
}

func getUploadRequestBody(
	task *DefaultUploadTask,
	file *os.File,
	fileTransferStats FileTransferStats,
	logger *observability.CoreLogger,
) (io.Reader, error) {
	stat, err := file.Stat()
	if err != nil {
		return nil, fmt.Errorf(
			"file transfer: upload: error when stat-ing %s: %v",
			task.Path,
			err,
		)
	}

	// Don't try to upload directories.
	if stat.IsDir() {
		return nil, fmt.Errorf(
			"file transfer: upload: cannot upload directory %v",
			task.Path,
		)
	}

	if task.Offset+task.Size > stat.Size() {
		// If the range exceeds the file size, there was some kind of error upstream.
		return nil, fmt.Errorf("file transfer: upload: offset + size exceeds the file size")
	}

	if task.Size == 0 {
		// If Size is 0, upload the remainder of the file.
		task.Size = stat.Size() - task.Offset
	}

	// Due to historical mistakes, net/http interprets a 0 value of
	// Request.ContentLength as "unknown" if the body is non-nil, and
	// doesn't send the Content-Length header which is usually required.
	//
	// To have it understand 0 as 0, the body must be set to nil or
	// the NoBody sentinel.
	var requestBody io.Reader
	if task.Size == 0 {
		requestBody = http.NoBody
	} else {
		if task.Size > math.MaxInt {
			return nil, fmt.Errorf("file transfer: file too large (%d bytes)", task.Size)
		}

		progress, err := wboperation.Get(task.Context).NewProgress()
		if err != nil {
			logger.CaptureError(fmt.Errorf("file transfer: %v", err))
		}

		requestBody = NewProgressReader(
			io.NewSectionReader(file, task.Offset, task.Size),
			task.Size,
			func(processed, total int64) {
				if task.ProgressCallback != nil {
					task.ProgressCallback(int(processed), int(total))
				}

				progress.SetBytesOfTotal(int(processed), int(total))

				fileTransferStats.UpdateUploadStats(FileUploadInfo{
					FileKind:      task.FileKind,
					Path:          task.Path,
					UploadedBytes: int64(processed),
					TotalBytes:    int64(total),
				})
			},
		)
	}
	return requestBody, nil
}
