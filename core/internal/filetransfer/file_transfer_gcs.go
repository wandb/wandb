package filetransfer

import (
	"context"

	"cloud.google.com/go/storage"
	"github.com/wandb/wandb/core/pkg/observability"
)

// GCSFileTransfer uploads or downloads files to/from GCS
type GCSFileTransfer struct {
	// client is the HTTP client for the file transfer
	client *storage.Client

	// logger is the logger for the file transfer
	logger *observability.CoreLogger

	// fileTransferStats is used to track upload/download progress
	fileTransferStats FileTransferStats
}

// NewGCSFileTransfer creates a new fileTransfer
func NewGCSFileTransfer(
	logger *observability.CoreLogger,
	fileTransferStats FileTransferStats,
) *GCSFileTransfer {
	ctx := context.Background()
	client, err := storage.NewClient(ctx)
	if err != nil {
		// TODO: Handle error.
		return nil
	}

	fileTransfer := &GCSFileTransfer{
		logger:            logger,
		client:            client,
		fileTransferStats: fileTransferStats,
	}
	return fileTransfer
}

// Upload uploads a file to the server
func (ft *GCSFileTransfer) Upload(task *Task) error {
	ft.logger.Debug("gcs file transfer: uploading file", "path", task.Path, "url", task.Url)

	return nil
}

// Download downloads a file from the server
func (ft *GCSFileTransfer) Download(task *Task) error {
	ft.logger.Debug("gcs reference file transfer: downloading file", "path", task.Path, "url", task.Url)

	return nil
}
