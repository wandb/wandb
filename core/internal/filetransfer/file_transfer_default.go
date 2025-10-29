package filetransfer

import (
	"context"
	"fmt"
	"io"
	"math"
	"net/http"
	"os"
	"path"
	"runtime"
	"strings"

	"github.com/hashicorp/go-retryablehttp"
	"github.com/wandb/wandb/core/internal/observability"
	"github.com/wandb/wandb/core/internal/wboperation"
	"golang.org/x/sync/errgroup"
)

const (
	DefaultMultipartDownloadThreshold = 2 * 1024 * 1024 * 1024 // 2 GiB
	DefaultMultipartDownloadPartSize  = 100 * 1024 * 1024      // 100 MiB
	httpStreamingChunkSize            = 1 * 1024 * 1024        // 1 MiB for streaming chunks
)

// DefaultFileTransfer uploads or downloads files to/from the server.
// It handles upload/download of normal artifacts (i.e. object store managed/acessed by wandb).
// It also handles download of reference artifacts using http(s).
type DefaultFileTransfer struct {
	// client is the HTTP client for the file transfer
	client *retryablehttp.Client

	// logger is the logger for the file transfer
	logger *observability.CoreLogger

	// fileTransferStats is used to track upload/download progress
	fileTransferStats FileTransferStats

	// multipartDownloadThreshold is the minimum size for download in multipart mode with parallel http range requests
	// Currently it always uses [DefaultMultipartDownloadThreshold] except for test.
	multipartDownloadThreshold int64

	// multipartDownloadPartSize is the size of each http range request
	// Currently it always uses [DefaultMultipartDownloadPartSize] except for test.
	multipartDownloadPartSize int64
}

// NewDefaultFileTransfer creates a new fileTransfer
func NewDefaultFileTransfer(
	client *retryablehttp.Client,
	logger *observability.CoreLogger,
	fileTransferStats FileTransferStats,
) *DefaultFileTransfer {
	fileTransfer := &DefaultFileTransfer{
		logger:                     logger,
		client:                     client,
		fileTransferStats:          fileTransferStats,
		multipartDownloadThreshold: DefaultMultipartDownloadThreshold,
		multipartDownloadPartSize:  DefaultMultipartDownloadPartSize,
	}
	return fileTransfer
}

// NewTestDefaultFileTransfer creates a new fileTransfer for testing with smaller files.
func NewTestDefaultFileTransfer(minMultipartDownloadSize int64, multipartDownloadChunkSize int64) *DefaultFileTransfer {
	return &DefaultFileTransfer{
		logger:                     observability.NewNoOpLogger(),
		client:                     retryablehttp.NewClient(),
		fileTransferStats:          NewFileTransferStats(),
		multipartDownloadThreshold: minMultipartDownloadSize,
		multipartDownloadPartSize:  multipartDownloadChunkSize,
	}
}

// Upload uploads a file to the server
func (ft *DefaultFileTransfer) Upload(task *DefaultUploadTask) error {
	ft.logger.Debug("default file transfer: uploading file", "path", task.Path, "url", task.Url)

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
		// Try to read the body to know the detail error message
		return attachErrorResponseBody("file transfer: upload: failed to upload: status: "+resp.Status,
			resp)
	}
	task.Response = resp

	return nil
}

// attachErrorResponseBody returns an error with the error prefix and the first 1024 bytes of the response body.
// It closes the response body after reading the first 1024 bytes.
func attachErrorResponseBody(errPrefix string, resp *http.Response) error {
	// Only read first 1024 bytes of error message
	body, err := io.ReadAll(io.LimitReader(resp.Body, 1024))
	resp.Body.Close()
	if err != nil {
		return fmt.Errorf("%s: error reading body: %s", errPrefix, err)
	}
	return fmt.Errorf("%s: body: %s", errPrefix, string(body))
}

// Download downloads a file from the server
func (ft *DefaultFileTransfer) Download(task *DefaultDownloadTask) error {
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

	if task.Size >= ft.multipartDownloadThreshold {
		return ft.DownloadMultipart(task, file)
	}
	return ft.downloadSerial(task, file)
}

// downloadSerial copy the http response body to the file using single request.
func (ft *DefaultFileTransfer) downloadSerial(task *DefaultDownloadTask, file *os.File) error {
	// TODO: redo it to use the progress writer, to track the download progress
	resp, err := ft.client.Get(task.Url)
	if err != nil {
		return err
	}
	task.Response = resp

	defer func(file io.ReadCloser) {
		if err := file.Close(); err != nil {
			ft.logger.CaptureError(
				fmt.Errorf(
					"file transfer: download: error closing response reader: %v",
					err,
				))
		}
	}(resp.Body)

	_, err = io.Copy(file, resp.Body)
	if err != nil {
		return err
	}
	return nil
}

// DownloadMultipart download the file using multiple http range requests.
// You should always use [Download] instead of this method unless you are testing file write errorh handling.
func (ft *DefaultFileTransfer) DownloadMultipart(task *DefaultDownloadTask, file WriterAt) error {
	// Split file into multiple http range requests and distribute to multiple workers
	requests := SplitHttpRanges(task.Size, ft.multipartDownloadPartSize)
	numWorkers := min(runtime.NumCPU(), len(requests))
	workerTasks, err := SplitWorkerTasks(len(requests), numWorkers)
	if err != nil {
		return fmt.Errorf("file transfer: download multipart: failed to split worker tasks: %w", err)
	}
	// Use channel to stream the chunks from download workers to the single file writer
	chunkChan := make(chan *FileChunk, numWorkers*10)

	// TODO: We should change the signature to pass the ctx as first argument instead of part of task struct
	ctx := task.Context

	// We have two error groups. One for download to make sure it close the channel to signal success completion to the file writer.
	// Another for download and file writer to make sure if one of the has error, the other one would stop.
	wg, ctx := errgroup.WithContext(ctx)
	wg.Go(func() error {
		defer close(chunkChan)

		downloadGroup, ctx := errgroup.WithContext(ctx)
		for workerID := range numWorkers {
			taskRange := workerTasks[workerID]
			downloadGroup.Go(func() error {
				for i, req := range requests[taskRange.Start:taskRange.End] {
					select {
					case <-ctx.Done():
						// One of the download worker or file writer has error, stop early
						return ctx.Err()
					default:
					}

					err := ft.downloadPart(ctx, task.Url, req, chunkChan)
					if err != nil {
						return fmt.Errorf("worker %d failed to download part %d: %w", workerID, taskRange.Start+i, err)
					}
				}
				return nil
			})
		}
		return downloadGroup.Wait()
	})

	// Flush file in a single goroutine.
	wg.Go(func() error {
		return WriteChunksToFile(ctx, file, chunkChan)
	})
	return wg.Wait()
}

// downloadPart downloads a single part using HTTP Range request and streams response body out to channel.
func (ft *DefaultFileTransfer) downloadPart(
	ctx context.Context,
	url string,
	reqRange httpRange,
	chunkChan chan<- *FileChunk,
) error {
	req, err := retryablehttp.NewRequest(http.MethodGet, url, nil)
	if err != nil {
		return err
	}

	req = req.WithContext(ctx)
	req.Header.Set("Range", fmt.Sprintf("bytes=%d-%d", reqRange.start, reqRange.end))

	resp, err := ft.client.Do(req)
	if err != nil {
		return err
	}
	defer resp.Body.Close()

	// Stream the response in small buffer instead of entire response body.
	buffer := make([]byte, httpStreamingChunkSize)
	offset := reqRange.start

	for {
		n, err := resp.Body.Read(buffer)
		if n > 0 {
			chunk := &FileChunk{
				Offset: offset,
				Data:   make([]byte, n),
			}
			copy(chunk.Data, buffer[:n])

			// Make sure we can cancel via context instead of blocking on writing to channel.
			select {
			case chunkChan <- chunk:
				offset += int64(n)
			case <-ctx.Done():
				return ctx.Err()
			}
		}

		if err == io.EOF {
			break
		}
		if err != nil {
			return err
		}
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
			int(task.Size),
			func(processed int, total int) {
				if task.ProgressCallback != nil {
					task.ProgressCallback(processed, total)
				}

				progress.SetBytesOfTotal(processed, total)

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

type ProgressReader struct {
	io.ReadSeeker
	len      int
	read     int
	callback func(processed, total int)
}

func NewProgressReader(
	reader io.ReadSeeker,
	size int,
	callback func(processed, total int),
) *ProgressReader {
	return &ProgressReader{
		ReadSeeker: reader,
		len:        size,
		callback:   callback,
	}
}

func (pr *ProgressReader) Read(p []byte) (int, error) {
	n, err := pr.ReadSeeker.Read(p)
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
	return int(pr.len)
}
