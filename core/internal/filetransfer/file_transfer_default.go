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
	"time"

	"github.com/hashicorp/go-retryablehttp"
	"github.com/wandb/wandb/core/internal/observability"
	"github.com/wandb/wandb/core/internal/wboperation"
	"golang.org/x/sync/errgroup"
)

const (
	// Parallel download thresholds
	s3MinMultiDownloadSize     = 2 << 30   // 2 GiB
	s3DefaultDownloadChunkSize = 100 << 20 // 100 MiB
	s3DefaultHTTPChunkSize     = 1 << 20   // 1 MiB
	s3MaxParts                 = 10000
	downloadQueueSize          = 500 // Max buffered chunks
)

// chunkData represents downloaded data with its file offset
type chunkData struct {
	Offset int64
	Data   []byte
}

// workerStats tracks statistics for a single download worker
type workerStats struct {
	WorkerID      int
	PartsComplete int
	BytesDownloaded int64
	NetworkTime   time.Duration
	StartTime     time.Time
	EndTime       time.Time
}

// downloadPart represents a chunk to download
type downloadPart struct {
	PartNumber int
	StartByte  int64
	EndByte    int64
	Size       int64
}

// DefaultFileTransfer uploads or downloads files to/from the server
type DefaultFileTransfer struct {
	// client is the HTTP client for the file transfer
	client            *retryablehttp.Client
	noKeepAliveClient *retryablehttp.Client

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
	// TODO: proper way to create the client, there is no common creating client package after https://github.com/wandb/wandb/pull/7090
	// TODO: the client passed in is from NewFileTransferManager https://github.com/wandb/wandb/blob/be8c808bd8ce7d6db6a5e2c703ae82018a5cf5c0/core/internal/stream/stream_init.go#L214
	tr := http.DefaultTransport.(*http.Transport).Clone()
	tr.DisableKeepAlives = true
	noKeepAliveClient := retryablehttp.NewClient()
	noKeepAliveClient.HTTPClient.Transport = tr
	noKeepAliveClient.Logger = logger

	fileTransfer := &DefaultFileTransfer{
		logger:            logger,
		client:            client,
		noKeepAliveClient: noKeepAliveClient,
		fileTransferStats: fileTransferStats,
	}
	return fileTransfer
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
		return fmt.Errorf("file transfer: upload: failed to upload: %s", resp.Status)
	}
	task.Response = resp

	return nil
}

// Download downloads a file from the server
func (ft *DefaultFileTransfer) Download(task *DefaultDownloadTask) error {
	ft.logger.Info("default file transfer: download started", "path", task.Path, "url", task.Url, "size", task.Size, "fileKind", task.FileKind)

	// Check if we should use parallel download based on task.Size
	if ft.shouldUseParallelDownload(task) {
		ft.logger.Info("using parallel download", "size", task.Size, "threshold", s3MinMultiDownloadSize)
		return ft.downloadParallel(task)
	}

	// Fallback to serial download for small files
	ft.logger.Info("using serial download", "size", task.Size, "threshold", s3MinMultiDownloadSize)
	return ft.downloadSerial(task)
}

// downloadSerial performs a serial download (original implementation)
func (ft *DefaultFileTransfer) downloadSerial(task *DefaultDownloadTask) error {
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

	_, err = io.Copy(file, resp.Body)
	if err != nil {
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

// shouldUseParallelDownload checks if file meets threshold for parallel download
func (ft *DefaultFileTransfer) shouldUseParallelDownload(task *DefaultDownloadTask) bool {
	// Use task.Size which already contains the file size
	// No need for HEAD request
	shouldUse := task.Size >= s3MinMultiDownloadSize && task.Size > 0
	ft.logger.Debug("checking parallel download eligibility", "size", task.Size, "threshold", s3MinMultiDownloadSize, "shouldUse", shouldUse)
	return shouldUse
}

// downloadParallel performs parallel download
func (ft *DefaultFileTransfer) downloadParallel(task *DefaultDownloadTask) error {
	ft.logger.Info("parallel download starting",
		"path", task.Path,
		"url", task.Url,
		"size", task.Size)

	// Calculate parts based on task.Size
	parts := ft.calculateDownloadParts(task.Size)
	// *2 because most work are IO bound
	numWorkers := min(runtime.NumCPU()*2, len(parts))

	ft.logger.Info("parallel download configuration",
		"numParts", len(parts),
		"numWorkers", numWorkers,
		"chunkSize", ft.getDownloadChunkSize(task.Size),
		"queueSize", downloadQueueSize)

	// Create output file
	dir := path.Dir(task.Path)
	ft.logger.Debug("creating directory for download", "dir", dir)
	if err := os.MkdirAll(dir, os.ModePerm); err != nil {
		ft.logger.Error("failed to create directory", "dir", dir, "error", err)
		return err
	}

	ft.logger.Debug("creating output file", "path", task.Path)
	file, err := os.Create(task.Path)
	if err != nil {
		ft.logger.Error("failed to create file", "path", task.Path, "error", err)
		return err
	}
	defer file.Close()

	// Setup channels and context
	ctx := context.Background()
	if task.Context != nil {
		ctx = task.Context
	}

	chunkQueue := make(chan chunkData, downloadQueueSize)

	// Create error group with shared context for all workers
	g, ctx := errgroup.WithContext(ctx)

	// Start download workers
	workerTasks := ft.splitDownloadTasks(parts, numWorkers)
	workerStatsChan := make(chan workerStats, numWorkers)
	ft.logger.Info("starting download workers", "numWorkers", numWorkers)
	for i, workerParts := range workerTasks {
		workerID := i
		taskParts := workerParts

		ft.logger.Debug("starting worker", "workerID", workerID, "numParts", len(taskParts))
		g.Go(func() error {
			stats := workerStats{
				WorkerID:  workerID,
				StartTime: time.Now(),
			}
			for _, part := range taskParts {
				networkStart := time.Now()
				if err := ft.downloadPart(ctx, task, part, chunkQueue); err != nil {
					ft.logger.Error("worker failed on part", "workerID", workerID, "partNumber", part.PartNumber, "error", err)
					return fmt.Errorf("worker %d failed on part %d: %w", workerID, part.PartNumber, err)
				}
				stats.NetworkTime += time.Since(networkStart)
				stats.PartsComplete++
				stats.BytesDownloaded += part.Size
			}
			stats.EndTime = time.Now()
			workerStatsChan <- stats
			return nil
		})
	}

	// Start a goroutine to close the channel when all downloads complete
	downloadComplete := make(chan error, 1)
	go func() {
		ft.logger.Info("waiting for all download workers to complete")
		err := g.Wait()
		close(workerStatsChan)
		
		// Collect and log worker statistics
		var totalNetworkTime time.Duration
		var totalBytesDownloaded int64
		var totalParts int
		for stats := range workerStatsChan {
			totalNetworkTime += stats.NetworkTime
			totalBytesDownloaded += stats.BytesDownloaded
			totalParts += stats.PartsComplete
			workerDuration := stats.EndTime.Sub(stats.StartTime)
			speed := float64(stats.BytesDownloaded) / stats.NetworkTime.Seconds() / 1048576 // MB/s
			ft.logger.Info("worker summary",
				"workerID", stats.WorkerID,
				"partsComplete", stats.PartsComplete,
				"bytesDownloaded", stats.BytesDownloaded,
				"networkTime", stats.NetworkTime,
				"totalTime", workerDuration,
				"avgSpeed", fmt.Sprintf("%.1f MB/s", speed))
		}
		
		if err != nil {
			ft.logger.Error("download workers failed", "error", err)
		} else {
			avgSpeed := float64(totalBytesDownloaded) / totalNetworkTime.Seconds() / 1048576
			ft.logger.Info("all workers completed",
				"totalParts", totalParts,
				"totalBytes", totalBytesDownloaded,
				"totalNetworkTime", totalNetworkTime,
				"avgNetworkSpeed", fmt.Sprintf("%.1f MB/s", avgSpeed))
		}
		ft.logger.Debug("closing chunk queue to signal writer to stop")
		close(chunkQueue)
		downloadComplete <- err
	}()

	// Use the main goroutine to write chunks to file
	ft.logger.Info("starting file writer in main goroutine")
	writeStartTime := time.Now()
	writerErr := ft.writeChunksToFile(file, chunkQueue, task)
	writeDuration := time.Since(writeStartTime)
	if writerErr == nil {
		writeSpeed := float64(task.Size) / writeDuration.Seconds() / 1048576
		ft.logger.Info("file write completed",
			"totalWriteTime", writeDuration,
			"avgWriteSpeed", fmt.Sprintf("%.1f MB/s", writeSpeed))
	}

	// Wait for download workers to complete
	downloadErr := <-downloadComplete

	// Return the first error encountered
	if writerErr != nil {
		ft.logger.Error("file writer failed", "error", writerErr)
		return writerErr
	}
	if downloadErr != nil {
		ft.logger.Error("download failed", "error", downloadErr)
		return downloadErr
	}

	ft.logger.Info("parallel download completed successfully")
	return nil
}

// downloadPart downloads a single part using Range header
func (ft *DefaultFileTransfer) downloadPart(
	ctx context.Context,
	task *DefaultDownloadTask,
	part downloadPart,
	chunkQueue chan<- chunkData,
) error {
	// Create range request: "bytes=0-104857599" (0-99MB)
	rangeHeader := fmt.Sprintf("bytes=%d-%d", part.StartByte, part.EndByte)

	req, err := retryablehttp.NewRequest(http.MethodGet, task.Url, nil)
	if err != nil {
		ft.logger.Error("failed to create request", "partNumber", part.PartNumber, "error", err)
		return err
	}
	req.Header.Set("Range", rangeHeader)

	// Add original headers from task
	for _, header := range task.Headers {
		parts := strings.SplitN(header, ":", 2)
		if len(parts) == 2 {
			req.Header.Set(parts[0], parts[1])
		}
	}

	// retryablehttp.Client handles retries automatically
	var resp *http.Response
	if os.Getenv("WANDB_DOWNLOAD_DISABLE_KEEPALIVE") == "true" {
		ft.logger.Info("Using no keep alive client for part", "partNumber", part.PartNumber)
		resp, err = ft.noKeepAliveClient.Do(req.WithContext(ctx))
	} else {
		resp, err = ft.client.Do(req.WithContext(ctx))
	}
	if err != nil {
		ft.logger.Error("HTTP request failed", "partNumber", part.PartNumber, "error", err)
		return err
	}
	defer resp.Body.Close()

	if resp.StatusCode != http.StatusPartialContent {
		ft.logger.Error("unexpected status code", "partNumber", part.PartNumber, "statusCode", resp.StatusCode, "expected", http.StatusPartialContent)
		return fmt.Errorf("expected 206 Partial Content, got %d", resp.StatusCode)
	}


	// Stream response in chunks
	offset := part.StartByte
	buffer := make([]byte, s3DefaultHTTPChunkSize) // 1MB buffer
	totalRead := int64(0)
	chunkCount := 0


	for {
		select {
		case <-ctx.Done():
			ft.logger.Warn("context cancelled while reading part", "partNumber", part.PartNumber, "totalRead", totalRead)
			return ctx.Err()
		default:
		}

		n, err := resp.Body.Read(buffer)
		if n > 0 {
			chunkCount++
			totalRead += int64(n)


			chunk := chunkData{
				Offset: offset,
				Data:   make([]byte, n),
			}
			copy(chunk.Data, buffer[:n])

			// Try to send chunk to queue
			select {
			case chunkQueue <- chunk:
				offset += int64(n)
				// Log if queue might be getting full
				if len(chunkQueue) > downloadQueueSize*8/10 {
					ft.logger.Warn("chunk queue getting full", "queueLen", len(chunkQueue), "queueCap", downloadQueueSize)
				}
			case <-ctx.Done():
				ft.logger.Warn("context cancelled while sending chunk", "partNumber", part.PartNumber, "totalRead", totalRead)
				return ctx.Err()
			}
		}

		if err == io.EOF {
			break
		} else if err != nil {
			ft.logger.Error("error reading part", "partNumber", part.PartNumber, "error", err, "totalRead", totalRead)
			return err
		}
	}

	return nil
}

// writeChunksToFile handles writing chunks to file
// Runs in the main goroutine - no locks needed
func (ft *DefaultFileTransfer) writeChunksToFile(
	file *os.File,
	chunkQueue <-chan chunkData,
	task *DefaultDownloadTask,
) error {
	writtenBytes := int64(0)
	chunkCount := 0
	lastLoggedBytes := int64(0)
	lastLogTime := time.Now()
	startTime := time.Now()
	totalWriteTime := time.Duration(0)
	minWriteTime := time.Duration(math.MaxInt64)
	maxWriteTime := time.Duration(0)

	ft.logger.Info("file writer started", "targetSize", task.Size)

	for {
		chunk, ok := <-chunkQueue
		if !ok {
			// Channel closed, all chunks written
			duration := time.Since(startTime)
			avgWriteTime := time.Duration(0)
			if chunkCount > 0 {
				avgWriteTime = totalWriteTime / time.Duration(chunkCount)
			}
			writeSpeed := float64(writtenBytes) / totalWriteTime.Seconds() / 1048576
			overallSpeed := float64(writtenBytes) / duration.Seconds() / 1048576
			
			ft.logger.Info("file write summary",
				"totalBytes", writtenBytes,
				"chunks", chunkCount,
				"totalTime", duration.Round(time.Millisecond),
				"totalWriteTime", totalWriteTime.Round(time.Millisecond),
				"avgWriteTime", avgWriteTime.Round(time.Microsecond),
				"minWriteTime", minWriteTime.Round(time.Microsecond),
				"maxWriteTime", maxWriteTime.Round(time.Microsecond),
				"diskWriteSpeed", fmt.Sprintf("%.1f MB/s", writeSpeed),
				"overallSpeed", fmt.Sprintf("%.1f MB/s", overallSpeed))
			return nil
		}

		chunkCount++

		// Seek to correct position (creates sparse file)
		if _, err := file.Seek(chunk.Offset, io.SeekStart); err != nil {
			ft.logger.Error("failed to seek", "offset", chunk.Offset, "error", err)
			return fmt.Errorf("failed to seek to offset %d: %w", chunk.Offset, err)
		}

		// Write chunk data
		writeStart := time.Now()
		if _, err := file.Write(chunk.Data); err != nil {
			ft.logger.Error("failed to write chunk", "offset", chunk.Offset, "size", len(chunk.Data), "error", err)
			return fmt.Errorf("failed to write chunk at offset %d: %w", chunk.Offset, err)
		}
		writeDuration := time.Since(writeStart)
		totalWriteTime += writeDuration
		if writeDuration < minWriteTime {
			minWriteTime = writeDuration
		}
		if writeDuration > maxWriteTime {
			maxWriteTime = writeDuration
		}

		// Update progress
		writtenBytes += int64(len(chunk.Data))

		// Log progress every 500MB and at least every 30 seconds
		timeSinceLastLog := time.Since(lastLogTime)
		if writtenBytes-lastLoggedBytes >= 524288000 || timeSinceLastLog >= 30*time.Second {
			progress := float64(writtenBytes) / float64(task.Size) * 100
			duration := time.Since(startTime)
			speed := float64(writtenBytes-lastLoggedBytes) / timeSinceLastLog.Seconds() / 1048576 // MB/s
			ft.logger.Info("file write progress",
				"progress", fmt.Sprintf("%.1f%%", progress),
				"written", fmt.Sprintf("%.1f GB", float64(writtenBytes)/1073741824),
				"speed", fmt.Sprintf("%.1f MB/s", speed),
				"elapsed", duration.Round(time.Second))
			lastLoggedBytes = writtenBytes
			lastLogTime = time.Now()
		}

		if task.ProgressCallback != nil {
			task.ProgressCallback(int(writtenBytes), int(task.Size))
		}

		// Update file transfer stats
		if ft.fileTransferStats != nil {
			ft.fileTransferStats.UpdateUploadStats(FileUploadInfo{
				FileKind:      task.FileKind,
				Path:          task.Path,
				UploadedBytes: writtenBytes,
				TotalBytes:    task.Size,
			})
		}
	}
}

// calculateDownloadParts splits file into parts for parallel download
func (ft *DefaultFileTransfer) calculateDownloadParts(fileSize int64) []downloadPart {
	chunkSize := ft.getDownloadChunkSize(fileSize)
	numParts := int(fileSize / chunkSize)
	if fileSize%chunkSize != 0 {
		numParts++
	}

	ft.logger.Debug("calculating download parts", "fileSize", fileSize, "chunkSize", chunkSize, "numParts", numParts)

	parts := make([]downloadPart, numParts)
	for i := 0; i < numParts; i++ {
		startByte := int64(i) * chunkSize
		endByte := min(startByte+chunkSize-1, fileSize-1)

		parts[i] = downloadPart{
			PartNumber: i + 1,
			StartByte:  startByte,
			EndByte:    endByte,
			Size:       endByte - startByte + 1,
		}
	}

	ft.logger.Debug("download parts calculated", "firstPart", parts[0], "lastPart", parts[len(parts)-1])
	return parts
}

// getDownloadChunkSize calculates the optimal chunk size
func (ft *DefaultFileTransfer) getDownloadChunkSize(fileSize int64) int64 {
	if fileSize < s3DefaultDownloadChunkSize*s3MaxParts {
		return s3DefaultDownloadChunkSize
	}
	// Calculate larger chunk size if needed
	chunkSize := int64(math.Ceil(float64(fileSize) / float64(s3MaxParts)))
	return int64(math.Ceil(float64(chunkSize)/4096) * 4096)
}

// splitDownloadTasks distributes parts among workers
func (ft *DefaultFileTransfer) splitDownloadTasks(parts []downloadPart, numWorkers int) [][]downloadPart {
	partsPerWorker := len(parts) / numWorkers
	workersWithOneMorePart := len(parts) % numWorkers

	workerTasks := make([][]downloadPart, numWorkers)
	partIndex := 0

	for i := 0; i < numWorkers; i++ {
		workerPartCount := partsPerWorker
		if i < workersWithOneMorePart {
			workerPartCount++
		}

		workerTasks[i] = parts[partIndex : partIndex+workerPartCount]
		partIndex += workerPartCount
	}

	return workerTasks
}
