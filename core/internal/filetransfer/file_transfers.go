package filetransfer

import (
	"github.com/hashicorp/go-retryablehttp"
	"github.com/wandb/wandb/core/internal/observability"
)

type FileTransfer interface {
	Upload(task *DefaultUploadTask) error
	Download(task *DefaultDownloadTask) error
}

type ReferenceArtifactFileTransfer interface {
	Upload(task *ReferenceArtifactUploadTask) error
	Download(task *ReferenceArtifactDownloadTask) error
}

// FileTransfers is a collection of file transfers by upload destination type.
type FileTransfers struct {
	// Default makes an HTTP request to the destination URL with the file contents.
	Default FileTransfer
	GCS     ReferenceArtifactFileTransfer
}

// NewFileTransfers creates a new fileTransfers
func NewFileTransfers(
	client *retryablehttp.Client,
	logger *observability.CoreLogger,
	fileTransferStats FileTransferStats,
) *FileTransfers {
	filetransfers := &FileTransfers{}

	defaultFileTransfer := NewDefaultFileTransfer(client, logger, fileTransferStats)
	filetransfers.Default = defaultFileTransfer

	gcsFileTransfer, err := NewGCSFileTransfer(nil, logger, fileTransferStats)
	if err == nil {
		filetransfers.GCS = gcsFileTransfer
	} else {
		logger.Error("Unable to set up GCS file transfer", "error", err)
	}

	return filetransfers
}
