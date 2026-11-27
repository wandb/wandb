package wbapi

import (
	"context"
	"net/http"

	"github.com/wandb/wandb/core/internal/filetransfer"
	spb "github.com/wandb/wandb/core/pkg/service_go_proto"
)

// FileTransferHandler responds to file transfer requests, such as
// downloading a file from a URL to a local path.
type FileTransferHandler struct {
	fileTransferManager filetransfer.FileTransferManager
}

func NewFileTransferHandler(
	fileTransferManager filetransfer.FileTransferManager,
) *FileTransferHandler {
	return &FileTransferHandler{fileTransferManager: fileTransferManager}
}

// HandleDownloadFile downloads a file from a URL to a local path.
//
// It blocks until the download completes or fails.
func (h *FileTransferHandler) HandleDownloadFile(
	ctx context.Context,
	request *spb.DownloadFileRequest,
) *spb.ApiResponse {
	done := make(chan struct{})
	task := &filetransfer.DefaultDownloadTask{
		OnComplete: func() { close(done) },
		Path:       request.GetPath(),
		Url:        request.GetUrl(),
		Size:       request.GetSize(),
		Context:    ctx,
	}

	h.fileTransferManager.AddTask(task)
	<-done

	if task.Err != nil {
		var httpStatus int32
		if task.Response != nil {
			httpStatus = int32(task.Response.StatusCode)
		}
		return apiErrorResponse(task.Err.Error(), httpStatus)
	}

	return &spb.ApiResponse{
		Response: &spb.ApiResponse_DownloadFileResponse{
			DownloadFileResponse: &spb.DownloadFileResponse{},
		},
	}
}

// HandleUploadFile uploads a local file to a URL.
//
// It blocks until the upload completes or fails.
func (h *FileTransferHandler) HandleUploadFile(
	ctx context.Context,
	request *spb.UploadFileRequest,
) *spb.ApiResponse {
	headers := make(http.Header, len(request.GetHeaders()))
	for key, value := range request.GetHeaders() {
		headers.Set(key, value)
	}

	done := make(chan struct{})
	task := &filetransfer.DefaultUploadTask{
		OnComplete: func() { close(done) },
		Path:       request.GetPath(),
		Url:        request.GetUrl(),
		Headers:    headers,
		Context:    ctx,
	}

	h.fileTransferManager.AddTask(task)
	<-done

	if task.Err != nil {
		var httpStatus int32
		if task.Response != nil {
			httpStatus = int32(task.Response.StatusCode)
		}
		return apiErrorResponse(task.Err.Error(), httpStatus)
	}

	return &spb.ApiResponse{
		Response: &spb.ApiResponse_UploadFileResponse{
			UploadFileResponse: &spb.UploadFileResponse{},
		},
	}
}
