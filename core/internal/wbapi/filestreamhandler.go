package wbapi

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"net/url"

	"github.com/hashicorp/go-retryablehttp"

	"github.com/wandb/wandb/core/internal/api"
	"github.com/wandb/wandb/core/internal/filestream"
	spb "github.com/wandb/wandb/core/pkg/service_go_proto"
)

// FileStreamHandler notifies the W&B backend about run-file uploads through
// the filestream API.
//
// The live-run filestream loop already sends an "uploaded" signal for every
// file it uploads. This handler performs the same notification for files
// uploaded outside a run, such as the public API's upload_file. Without it,
// the bytes land in the object store but self-hosted deployments that lack
// object-store notifications never register the file with the run.
type FileStreamHandler struct {
	apiClient api.RetryableClient
	baseURL   *url.URL
}

func NewFileStreamHandler(
	apiClient api.RetryableClient,
	baseURL *url.URL,
) *FileStreamHandler {
	return &FileStreamHandler{apiClient: apiClient, baseURL: baseURL}
}

// HandleMarkRunFilesUploaded tells the backend that run files finished
// uploading by posting the filestream "uploaded" field.
func (h *FileStreamHandler) HandleMarkRunFilesUploaded(
	ctx context.Context,
	request *spb.MarkRunFilesUploadedRequest,
) *spb.ApiResponse {
	files := request.GetFiles()
	if len(files) == 0 {
		return markRunFilesUploadedResponse()
	}

	body, err := json.Marshal(&filestream.FileStreamRequestJSON{Uploaded: files})
	if err != nil {
		return apiErrorResponse(
			fmt.Sprintf("filestreamhandler: error marshaling request: %v", err), 0)
	}

	path := fmt.Sprintf(
		"files/%s/%s/%s/file_stream",
		request.GetEntity(),
		request.GetProject(),
		request.GetRunId(),
	)
	req, err := retryablehttp.NewRequestWithContext(
		ctx,
		http.MethodPost,
		h.baseURL.JoinPath(path).String(),
		bytes.NewReader(body),
	)
	if err != nil {
		return apiErrorResponse(
			fmt.Sprintf("filestreamhandler: error constructing request: %v", err), 0)
	}
	req.Header.Set("Content-Type", "application/json")

	resp, err := h.apiClient.Do(req)
	if err != nil {
		return apiErrorResponse(
			fmt.Sprintf("filestreamhandler: error making HTTP request: %v", err), 0)
	}
	defer func() { _ = resp.Body.Close() }()

	if resp.StatusCode < 200 || resp.StatusCode >= 300 {
		errBody, _ := io.ReadAll(io.LimitReader(resp.Body, 1<<10))
		return apiErrorResponse(
			fmt.Sprintf(
				"filestreamhandler: failed to notify of uploaded files: %s: %s",
				resp.Status,
				string(errBody),
			),
			int32(resp.StatusCode),
		)
	}

	return markRunFilesUploadedResponse()
}

func markRunFilesUploadedResponse() *spb.ApiResponse {
	return &spb.ApiResponse{
		Response: &spb.ApiResponse_MarkRunFilesUploadedResponse{
			MarkRunFilesUploadedResponse: &spb.MarkRunFilesUploadedResponse{},
		},
	}
}
