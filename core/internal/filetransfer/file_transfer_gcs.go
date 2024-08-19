package filetransfer

import (
	"context"
	"errors"
	"fmt"
	"net/url"

	"github.com/wandb/wandb/core/pkg/observability"
)

type GCSClient interface{}

// GCSFileTransfer uploads or downloads files to/from GCS
type GCSFileTransfer struct {
	// client is the HTTP client for the file transfer
	client GCSClient

	// logger is the logger for the file transfer
	logger *observability.CoreLogger

	// fileTransferStats is used to track upload/download progress
	fileTransferStats FileTransferStats

	// background context is used to create a reader and get the client
	ctx context.Context
}

var ErrObjectIsDirectory = errors.New("object is a directory and cannot be downloaded")

// NewGCSFileTransfer creates a new fileTransfer
func NewGCSFileTransfer(
	client GCSClient,
	logger *observability.CoreLogger,
	fileTransferStats FileTransferStats,
) *GCSFileTransfer {
	ctx := context.Background()
	fileTransfer := &GCSFileTransfer{
		logger:            logger,
		client:            client,
		fileTransferStats: fileTransferStats,
		ctx:               ctx,
	}
	return fileTransfer
}

// CanHandle returns true if GCSFileTransfer can upload/download the task
func (ft *GCSFileTransfer) CanHandle(task *ReferenceArtifactTask) bool {
	reference := *task.Reference
	uriParts, err := url.Parse(reference)
	if err != nil {
		return false
	} else if uriParts.Scheme == "gs" {
		return true
	}
	return false
}

// Upload uploads a file to the server
func (ft *GCSFileTransfer) Upload(task *ReferenceArtifactUploadTask) error {
	ft.logger.Debug("gcs file transfer: uploading file", "path", task.Path)

	return fmt.Errorf("not implemented yet")
}

// Download downloads a file from the server
func (ft *GCSFileTransfer) Download(task *ReferenceArtifactDownloadTask) error {
	ft.logger.Debug("gcs file transfer: downloading file", "path", task.Path, "ref", task.Reference)

	return fmt.Errorf("not implemented yet")
}
