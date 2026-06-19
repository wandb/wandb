package wbapi

import (
	"context"
	"path/filepath"
	"sync"
	"sync/atomic"
	"time"

	"github.com/wandb/wandb/core/internal/filetransfer"
	"github.com/wandb/wandb/core/internal/wboperation"
	spb "github.com/wandb/wandb/core/pkg/service_go_proto"
)

// completedDownloadRetention bounds how long a finished download that the
// client never polled to completion lingers in memory.
const completedDownloadRetention = 5 * time.Minute

// FileTransferHandler responds to file download requests.
//
// Downloads run asynchronously on the file transfer subsystem's worker pool:
// a start request schedules the download and returns immediately, and the
// client polls for progress and completion. This keeps long downloads off the
// API request path so they do not block unrelated requests.
type FileTransferHandler struct {
	fileTransferManager filetransfer.FileTransferManager

	// nextRequestID assigns a unique id to each download.
	nextRequestID atomic.Int32

	// mu guards downloads.
	mu sync.Mutex

	// downloads holds in-flight and finished-but-unpolled downloads by id.
	downloads map[int32]*fileDownload
}

// fileDownload tracks a single asynchronous download.
type fileDownload struct {
	// operations carries the download's progress, reported as OperationStats.
	operations *wboperation.WandbOperations

	// cancel releases the download's context.
	cancel context.CancelFunc

	mu         sync.Mutex
	done       bool
	errMsg     string
	finishedAt time.Time
}

func NewFileTransferHandler(
	fileTransferManager filetransfer.FileTransferManager,
) *FileTransferHandler {
	return &FileTransferHandler{
		fileTransferManager: fileTransferManager,
		downloads:           make(map[int32]*fileDownload),
	}
}

// HandleStartFileDownload schedules a download and returns its id immediately.
func (h *FileTransferHandler) HandleStartFileDownload(
	request *spb.StartFileDownloadRequest,
) *spb.ApiResponse {
	h.sweepCompleted()

	// The download outlives this request, so it must not use the request's
	// context, which is cancelled once we return.
	ctx, cancel := context.WithCancel(context.Background())
	operations := wboperation.NewOperations()
	operation := operations.New("downloading " + filepath.Base(request.GetPath()))

	download := &fileDownload{operations: operations, cancel: cancel}

	task := &filetransfer.DefaultDownloadTask{
		Path:    request.GetPath(),
		Url:     request.GetUrl(),
		Size:    request.GetSize(),
		Context: operation.Context(ctx),
	}
	task.OnComplete = func() {
		operation.Finish()
		download.mu.Lock()
		defer download.mu.Unlock()
		download.done = true
		download.finishedAt = time.Now()
		if task.Err != nil {
			download.errMsg = task.Err.Error()
		}
	}

	requestID := h.nextRequestID.Add(1)
	h.mu.Lock()
	h.downloads[requestID] = download
	h.mu.Unlock()

	h.fileTransferManager.AddTask(task)

	return &spb.ApiResponse{
		Response: &spb.ApiResponse_StartFileDownloadResponse{
			StartFileDownloadResponse: &spb.StartFileDownloadResponse{
				RequestId: requestID,
			},
		},
	}
}

// HandleFileDownloadStatus reports a download's progress and completion.
//
// Once it reports a finished download, the download is forgotten, so the
// client should stop polling after observing done.
func (h *FileTransferHandler) HandleFileDownloadStatus(
	request *spb.FileDownloadStatusRequest,
) *spb.ApiResponse {
	requestID := request.GetRequestId()

	h.mu.Lock()
	download, ok := h.downloads[requestID]
	h.mu.Unlock()

	if !ok {
		return apiErrorResponse("file download not found", 0)
	}

	download.mu.Lock()
	done := download.done
	errMsg := download.errMsg
	download.mu.Unlock()

	if done {
		h.mu.Lock()
		delete(h.downloads, requestID)
		h.mu.Unlock()
		download.cancel()
	}

	return &spb.ApiResponse{
		Response: &spb.ApiResponse_FileDownloadStatusResponse{
			FileDownloadStatusResponse: &spb.FileDownloadStatusResponse{
				Done:           done,
				Error:          errMsg,
				OperationStats: download.operations.ToProto(),
			},
		},
	}
}

// sweepCompleted forgets finished downloads that were never polled to
// completion, bounding memory for clients that abandon downloads.
func (h *FileTransferHandler) sweepCompleted() {
	now := time.Now()

	h.mu.Lock()
	defer h.mu.Unlock()
	for id, download := range h.downloads {
		download.mu.Lock()
		stale := download.done &&
			now.Sub(download.finishedAt) > completedDownloadRetention
		download.mu.Unlock()
		if stale {
			download.cancel()
			delete(h.downloads, id)
		}
	}
}
